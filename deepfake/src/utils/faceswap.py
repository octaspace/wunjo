import os
import sys
import cv2
import uuid
import math
import numpy as np
import torch
from tqdm import tqdm
import onnxruntime

import insightface

from concurrent.futures import ThreadPoolExecutor
import threading

root_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(root_path, "deepfake"))
from src.face3d.recognition import FaceRecognition
from src.utils.nudenet import NudeDetector
sys.path.pop(0)


class FaceSwapDeepfake:
    """
    Face swap by one photo
    """
    def __init__(self, model_path, face_swap_model_path, similarface = False, similar_coeff=0.95, device="cpu"):
        """
        Initialization
        :param model_path: path to model deepfake where will be download face recognition
        :param face_swap_model_path: path to face swap model
        """
        self.device = device
        self.face_recognition = FaceRecognition(model_path)
        self.access_providers = onnxruntime.get_available_providers()
        self.face_swap_model = self.load(face_swap_model_path)
        self.filter_model = NudeDetector(providers=self.access_providers if self.device == "cuda" else None)
        self.face_target_fields = None
        self.similarface = similarface
        self.lock = threading.Lock()  # Create a lock
        self.progress = 0  # Initialize a progress counter
        self.similar_coeff = similar_coeff

    def load(self, face_swap_model_path):
        """
        Load model ONNX face swap
        :param face_swap_model_path: path to face swap model
        :return: loaded model
        """
        # use cpu as with cuda on onnx can be problem
        if "CUDAExecutionProvider" in self.access_providers:
            provider = ["CUDAExecutionProvider"] if self.device == "cuda" else ["CPUExecutionProvider"]
        else:
            provider = ["CPUExecutionProvider"]

        return insightface.model_zoo.get_model(face_swap_model_path, providers=provider)

    @staticmethod
    def get_real_crop_box(frame, squareFace):
        """
        Get real crop box
        :param frame:
        :return:
        """
        if squareFace is not None:
            # real size
            originalHeight, originalWidth, _ = frame.shape

            canvasWidth = squareFace["canvasWidth"]
            canvasHeight = squareFace["canvasHeight"]
            # Calculate the scale factor
            scaleFactorX = originalWidth / canvasWidth
            scaleFactorY = originalHeight / canvasHeight

            # Calculate the new position and size of the square face on the original image
            # Convert canvas square face coordinates to original image coordinates
            newX1 = squareFace['x'] * scaleFactorX
            newX2 = (squareFace['x'] + 1) * scaleFactorX  # 1 is width
            newY1 = squareFace['y'] * scaleFactorY
            newY2 = (squareFace['y'] + 1) * scaleFactorY  # 1 is height

            # Calculate center point
            center_x = (newX1 + newX2) / 2
            center_y = (newY1 + newY2) / 2

            return int(center_x), int(center_y)
        return None, None

    def face_detect_with_alignment_from_source_frame(self, frame, face_fields=None):
        x_center, y_center = self.get_real_crop_box(frame, face_fields)
        dets = self.face_recognition.get_faces(frame)
        if not dets:
            raise FaceNotDetectedError("Face is not detected!")
        # it means what user will use multiface
        if x_center is None or y_center is None:
            return dets[0]
        else:
            distances = []
            for j, face in enumerate(dets):
                x1, y1, x2, y2 = face.bbox
                distance = abs((x1 + x2) / 2 - x_center) + abs((y1 + y2) / 2 - y_center)
                distances.append(distance)
                if x1 <= x_center <= x2 and y1 <= y_center <= y2:
                    return face
            else:
                if len(distances) > 0:
                    # Get point with minimum distance
                    min_index = min(range(len(distances)), key=distances.__getitem__)
                    return dets[min_index]

        raise FaceNotDetectedError("Face is not detected in user crop field!")

    def get_smoothened_boxes(self, boxes: np.ndarray, T: int = 5):
        """
        Get smoothened boxes
        :param boxes: frames with face boxes
        :param T: smooth windows size
        :return: list of processed frames, fps of the video
        """
        for i in range(len(boxes)):
            if i + T > len(boxes):
                window = boxes[len(boxes) - T:]
            else:
                window = boxes[i: i + T]
            boxes[i] = np.mean(window, axis=0)
        return boxes

    def get_min_distance(self, image, threshold=0.35):
        # real size
        originalHeight, originalWidth, _ = image.shape
        # Calculate the diagonal of the image
        diagonal = math.sqrt(originalHeight**2 + originalWidth**2)
        # Return the threshold percentage of the diagonal
        return diagonal * threshold

    @staticmethod
    def get_center(face):
        x1, y1, x2, y2 = face.bbox
        return int((x1 + x2) / 2), int((y1 + y2) / 2)

    @staticmethod
    def euclidean_distance(point1, point2):
        return math.sqrt((point1[0] - point2[0]) ** 2 + (point1[1] - point2[1]) ** 2)

    def face_detect_with_alignment_crop(self, image_files, face_fields):
        """
        Detect faces to swap if face_fields
        :param image_files: list of file paths of target images
        :param face_fields: crop target face
        :return:
        """
        predictions = []
        face_embedding_list = []
        face_gender = None

        # Read the first image to get the center
        first_image = cv2.imread(image_files[0])
        x_center, y_center = self.get_real_crop_box(first_image, face_fields)
        min_distance = self.get_min_distance(first_image)

        for n, image_file in enumerate(tqdm(image_files)):
            image = cv2.imread(image_file)
            dets = self.face_recognition.get_faces(image)
            if not dets:
                predictions.append([None])
                continue
            # this is init first face
            if x_center is None or y_center is None:
                face = dets[0]  # get first face
                x1, y1, x2, y2 = face.bbox
                face_gender = face.gender  # face gender
                predictions.append([face])  # prediction
                face_embedding_list += [face.normed_embedding]
                x_center = int((x1 + x2) / 2)  # set new center
                y_center = int((y1 + y2) / 2)  # set new center
            elif not face_embedding_list:  # not face yet, set new face
                for face in dets:
                    x1, y1, x2, y2 = face.bbox
                    if x1 <= x_center <= x2 and y1 <= y_center <= y2:
                        face_gender = face.gender  # face gender
                        predictions.append([face])  # prediction
                        face_embedding_list += [face.normed_embedding]
                        x_center = int((x1 + x2) / 2)  # set new center
                        y_center = int((y1 + y2) / 2)  # set new center
                        break
                else:
                    if n == 0:
                        closest_face = None
                        for face in dets:
                            face_center = self.get_center(face)
                            distance = self.euclidean_distance((x_center, y_center), face_center)
                            if distance < min_distance:
                                min_distance = distance
                                closest_face = face
                        if closest_face:
                            face_gender = closest_face.gender  # face gender
                            predictions.append([closest_face])  # prediction
                            face_embedding_list += [closest_face.normed_embedding]
                            x1, y1, x2, y2 = closest_face.bbox
                            x_center = int((x1 + x2) / 2)  # set new center
                            y_center = int((y1 + y2) / 2)  # set new center
            else:  # here is already recognition
                local_face_param = []
                for i, face in enumerate(dets):
                    x1, y1, x2, y2 = face.bbox
                    x_center = int((x1 + x2) / 2)  # set new center
                    y_center = int((y1 + y2) / 2)  # set new center
                    normed_embedding = face.normed_embedding
                    is_similar = self.face_recognition.is_similar_face(normed_embedding, face_embedding_list, self.similar_coeff)
                    if x1 <= x_center <= x2 and y1 <= y_center <= y2:
                        local_face_param += [{
                            "is_center": True, "is_gender": face_gender == face.gender, "is_embed": is_similar,
                            "bbox": face.bbox, "gender": face.gender, "embed": normed_embedding, "id": i
                        }]
                    else:
                        local_face_param += [{
                            "is_center": False, "is_gender": face_gender == face.gender, "is_embed": is_similar,
                            "bbox": face.bbox, "gender": face.gender, "embed": normed_embedding, "id": i
                        }]
                local_predictions = []
                for param in local_face_param:
                    if (param["is_center"] or param["is_gender"]) and param["is_embed"]:
                        # this predicted
                        x1, y1, x2, y2 = param["bbox"]
                        face_gender = param["gender"]  # face gender
                        # predictions.append([dets[param["id"]]])  # prediction
                        local_predictions.append(dets[param["id"]])
                        face_embedding_list += [param["embed"]]
                        x_center = int((x1 + x2) / 2)  # set new center
                        y_center = int((y1 + y2) / 2)  # set new center
                        if not self.similarface:  # if user want to get only one face in frame
                            break
                if len(local_predictions) > 0:
                    predictions.append(local_predictions)
                else:
                    predictions.append([None])

        return predictions

    def face_detect_with_alignment_all(self, image_files):
        """
        Detect all faces in each image
        :param image_files: list of file paths of images
        :return: list of detected faces for each image
        """
        predictions = []
        for image_file in tqdm(image_files):
            image = cv2.imread(image_file)
            dets = self.face_recognition.get_faces(image)
            if not dets:
                predictions.append([None])
                continue
            predictions.append(dets)
        return predictions

    def process_frame(self, args):
        frame, face_det_result, source_face, progress_bar, output_directory, idx = args
        tmp_frame = frame.copy()
        if self.filter_model.status(tmp_frame):
            for face in face_det_result:
                if face is None:
                    break
                else:
                    tmp_frame = self.face_swap_model.get(tmp_frame, face, source_face, paste_back=True)
        else:
            print("Face swap cannot be applied to nude or explicit content. Please upload images with appropriate content.")
        # Save the frame with zero-padded filename
        filename = os.path.join(output_directory, f"frame_{idx:04d}.png")
        cv2.imwrite(filename, tmp_frame)
        with self.lock:
            self.progress += 1
            progress_bar.update(1)  # Update progress bar in a thread-safe manner
        return filename

    def swap_video(self, target_frames_path, source_face, target_face_fields, save_file: str, multiface=False, fps=30, start_frame=None, end_frame=None, video_format=".mp4"):
        if "CUDAExecutionProvider" in self.access_providers and torch.cuda.is_available() and 'cpu' not in os.environ.get('WUNJO_TORCH_DEVICE', 'cpu'):
            # thread will not work correct with GPU
            return self.swap_video_cuda(target_frames_path, source_face, target_face_fields, save_file, multiface, fps, start_frame, end_frame, video_format)
        else:
            return self.swap_video_thread(target_frames_path, source_face, target_face_fields, save_file, multiface, fps, start_frame, end_frame, video_format)

    def swap_video_thread(self, target_frames_path, source_face, target_face_fields, save_path: str, multiface=False, fps=30, start_frame=None, end_frame=None, video_format=".mp4"):
        """
        Face swap video with Threads. Will not work with CUDA
        :param target_frames_path: directory containing target frames
        :param source_face: source face
        :param target_face_fields: crop field for target face
        :param save_file: save file path
        :param multiface: bool use swap all face or use target crop
        :param fps: video fps
        :param video_format: video format
        :return:
        """
        file_name = str(uuid.uuid4()) + '.mp4'
        save_file = os.path.join(save_path, file_name)
        frame_save_path = os.path.join(save_path, "faceswap_frames")
        os.makedirs(frame_save_path, exist_ok=True)

        # Get a list of all frame files in the target_frames_path directory
        frame_files = sorted([os.path.join(target_frames_path, fname) for fname in os.listdir(target_frames_path) if fname.endswith('.jpg') or fname.endswith('.png')])
        full_frame_files = frame_files.copy()

        if start_frame and end_frame:
            frame_files = frame_files[start_frame:end_frame]

        # Read the first frame to get the dimensions
        first_frame = cv2.imread(frame_files[0])
        frame_h, frame_w = first_frame.shape[:-1]

        if video_format == '.mp4':
            fourcc = cv2.VideoWriter_fourcc(*'mp4v')
        elif video_format == '.avi':
            fourcc = cv2.VideoWriter_fourcc(*'XVID')
        else:
            raise ValueError("Unsupported video format: {}".format(video_format))

        out = cv2.VideoWriter(save_file, fourcc, fps, (frame_w, frame_h))

        # Adjust the way we get face detection results
        if multiface:
            print("Getting all face...")
            face_det_results = self.face_detect_with_alignment_all(frame_files)
        else:
            print("Getting target face...")
            face_det_results = self.face_detect_with_alignment_crop(frame_files, target_face_fields)

        print("Starting face swap...")

        progress_bar = tqdm(total=len(frame_files), unit='it', unit_scale=True)

        with ThreadPoolExecutor(max_workers=4) as executor:
            processed_frame_files = list(executor.map(self.process_frame, [
                (cv2.imread(frame_files[i]), face_det_results[i], source_face, progress_bar, frame_save_path, i) for i
                in range(len(frame_files))
            ]))

        progress_bar.close()

        processed_frame_files.sort()  # Ensure files are in the correct order

        if start_frame:
            for frame_file in full_frame_files[:start_frame]:
                frame = cv2.imread(frame_file)
                out.write(frame)

        for frame_file in processed_frame_files:
            frame = cv2.imread(frame_file)
            out.write(frame)

        if end_frame:
            for frame_file in full_frame_files[end_frame:]:
                frame = cv2.imread(frame_file)
                out.write(frame)

        out.release()
        print("Face swap processing finished...")
        return file_name

    def swap_video_cuda(self, target_frames_path, source_face, target_face_fields, save_path: str, multiface=False, fps=30, start_frame=None, end_frame=None, video_format=".mp4"):
        """Face swap video without Threads"""
        file_name = str(uuid.uuid4()) + '.mp4'
        save_file = os.path.join(save_path, file_name)

        # Get a list of all frame files in the target_frames_path directory
        frame_files = sorted([os.path.join(target_frames_path, fname) for fname in os.listdir(target_frames_path) if fname.endswith('.png')])
        full_frame_files = frame_files.copy()

        if start_frame and end_frame:
            frame_files = frame_files[start_frame:end_frame]

        # Read the first frame to get the dimensions
        first_frame = cv2.imread(frame_files[0])
        frame_h, frame_w = first_frame.shape[:-1]

        if video_format == '.mp4':
            fourcc = cv2.VideoWriter_fourcc(*'mp4v')
        elif video_format == '.avi':
            fourcc = cv2.VideoWriter_fourcc(*'XVID')
        else:
            raise ValueError("Unsupported video format: {}".format(video_format))

        out = cv2.VideoWriter(save_file, fourcc, fps, (frame_w, frame_h))

        # Adjust the way we get face detection results
        if multiface:
            print("Getting all face...")
            face_det_results = self.face_detect_with_alignment_all(frame_files)
        else:
            print("Getting target face...")
            face_det_results = self.face_detect_with_alignment_crop(frame_files, target_face_fields)

        print("Starting face swap...")
        progress_bar = tqdm(total=len(full_frame_files), unit='it', unit_scale=True)

        if start_frame:
            for frame_path in full_frame_files[:start_frame]:
                tmp_frame = cv2.imread(frame_path)
                out.write(tmp_frame)
                progress_bar.update(1)

        for i, dets in enumerate(face_det_results):
            tmp_frame = cv2.imread(frame_files[i])
            if self.filter_model.status(tmp_frame):
                for face in dets:
                    if face is None:
                        break
                    else:
                        tmp_frame = self.face_swap_model.get(tmp_frame, face, source_face, paste_back=True)
            else:
                print("Face swap cannot be applied to nude or explicit content. Please upload images with appropriate content.")
            out.write(tmp_frame)
            progress_bar.update(1)

        if end_frame:
            for frame_path in full_frame_files[end_frame:]:
                tmp_frame = cv2.imread(frame_path)
                out.write(tmp_frame)
                progress_bar.update(1)

        out.release()
        print("Face swap processing finished...")
        progress_bar.close()

        return file_name

    def swap_image(self, target_frame, source_face, face_fields, save_dir: str, multiface=False):
        save_file = os.path.join(save_dir, "swapped_image.png")
        if self.filter_model.status(target_frame):
            x_center, y_center = self.get_real_crop_box(target_frame, face_fields)
            dets = self.face_recognition.get_faces(target_frame)
            if not dets:
                raise FaceNotDetectedError("Face is not detected in target image!")

            if x_center is None or y_center is None or multiface:
                for face in dets:
                    target_frame = self.face_swap_model.get(target_frame, face, source_face, paste_back=True)
                else:
                    cv2.imwrite(save_file, target_frame)
                    return target_frame
            else:
                distances = []
                for face in dets:
                    x1, y1, x2, y2 = face.bbox
                    distance = abs((x1 + x2) / 2 - x_center) + abs((y1 + y2) / 2 - y_center)
                    distances.append(distance)
                    if x1 <= x_center <= x2 and y1 <= y_center <= y2:
                        target_frame = self.face_swap_model.get(target_frame, face, source_face, paste_back=True)
                        cv2.imwrite(save_file, target_frame)
                        return target_frame
                else:
                    if len(distances) > 0:
                        # Get point with minimum distance
                        min_index = min(range(len(distances)), key=distances.__getitem__)
                        target_frame = self.face_swap_model.get(target_frame, dets[min_index], source_face, paste_back=True)
                        cv2.imwrite(save_file, target_frame)
                        return target_frame
        else:
            print("Face swap cannot be applied to nude or explicit content. Please upload images with appropriate content.")
            cv2.imwrite(save_file, target_frame)
            return target_frame

        raise FaceNotDetectedError("Face is not detected in user crop field in target image!")


class FaceNotDetectedError(Exception):
    pass