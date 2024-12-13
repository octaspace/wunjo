import os
import sys

# For portable version use HOME = os.environ.get('WUNJO_HOME', os.path.dirname(os.path.abspath(__file__)))
HOME = os.environ.get('WUNJO_HOME', os.path.expanduser("~"))

# Determine the cache directory based on the OS
CACHE_FOLDER = os.path.join(HOME, ".cache")
MEDIA_FOLDER = os.path.join(CACHE_FOLDER, 'wunjo')
if not os.path.exists(MEDIA_FOLDER):
    os.makedirs(MEDIA_FOLDER)

SETTING_FOLDER = os.path.join(MEDIA_FOLDER, 'setting')
if not os.path.exists(SETTING_FOLDER):
    os.makedirs(SETTING_FOLDER)

ALL_MODEL_FOLDER = os.path.join(MEDIA_FOLDER, 'all_models')
if not os.path.exists(ALL_MODEL_FOLDER):
    os.makedirs(ALL_MODEL_FOLDER)

TMP_FOLDER = os.path.join(MEDIA_FOLDER, 'tmp')
if not os.path.exists(TMP_FOLDER):
    os.makedirs(TMP_FOLDER)

# FFMPEG DIR
if sys.platform == 'win32':
    os.environ['FFMPEG_TEMP_DIR'] = TMP_FOLDER

# CONTENT FOLDERS
CONTENT_FOLDER = os.path.join(MEDIA_FOLDER, "content")
if not os.path.exists(CONTENT_FOLDER):
    os.makedirs(CONTENT_FOLDER)

CONTENT_FACE_SWAP_FOLDER_NAME = "face_swap"
CONTENT_LIP_SYNC_FOLDER_NAME = "lip_sync"
CONTENT_REMOVE_BACKGROUND_FOLDER_NAME = "remove_background"
CONTENT_REMOVE_OBJECT_FOLDER_NAME = "remove_object"
CONTENT_ENHANCEMENT_FOLDER_NAME = "enhancement"
CONTENT_AVATARS_FOLDER_NAME = "avatars"
CONTENT_ANALYSIS_NAME = "analysis"
CONTENT_SEPARATOR_FOLDER_NAME = "separator"
CONTENT_GENERATION_FOLDER_NAME = "generation"

# Method names without folder
CONTENT_IMG2IMG_NAME = "img2img"
CONTENT_TXT2IMG_NAME = "txt2img"
CONTENT_OUTPAINT_NAME = "outpaint"
