import logging
import os
from dotenv import load_dotenv
import cloudinary
import cloudinary.uploader
import cloudinary.api
import cloudinary.utils

load_dotenv()

logger = logging.getLogger(__name__)

_cloudinary_configured = False


def init_s3(app):
    global _cloudinary_configured
    cloudinary_url = os.environ.get('CLOUDINARY_URL')

    if cloudinary_url and not 'your_cloud_name' in cloudinary_url:
        cloudinary.config(cloudinary_url=cloudinary_url, secure=True)
        _cloudinary_configured = True
        app.config['USE_S3'] = True
    else:
        _cloudinary_configured = False
        app.config['USE_S3'] = False


def is_s3_enabled():
    return _cloudinary_configured


def upload_to_s3(file, folder='uploads'):
    """Upload a file to Cloudinary.

    Returns (public_id, resource_type) on success, or (None, None) when
    upload is unavailable/fails.
    """
    if not is_s3_enabled():
        return None, None

    try:
        result = cloudinary.uploader.upload(file, folder=folder, resource_type='auto')
        return result.get('public_id'), result.get('resource_type', 'image')
    except Exception as e:  # noqa: BLE001
        logger.error("Cloudinary upload failed: %s", e)
        return None, None


def delete_from_s3(public_id):
    if not is_s3_enabled() or not public_id:
        return False

    try:
        cloudinary.uploader.destroy(public_id)
        return True
    except Exception as e:  # noqa: BLE001
        logger.error("Cloudinary delete failed for '%s': %s", public_id, e)
        return False


def get_media_url(filepath, media_type='image'):
    if not filepath:
        return ''

    if is_s3_enabled() and not filepath.startswith('static/upload/'):
        # Auto-detect video assets by public_id extension as a fallback so
        # video URLs resolve with the correct resource_type even when the
        # caller does not pass media_type explicitly.
        if media_type != 'video' and str(filepath).lower().endswith(
                ('.mp4', '.mov', '.avi', '.webm', '.m4v', '.mkv')):
            media_type = 'video'
        resource_type = 'video' if media_type == 'video' else 'image'
        if resource_type == 'image':
            # Serve images optimized (auto format + quality) via Cloudinary
            # transforms without blocking the URL render.
            url, _ = cloudinary.utils.cloudinary_url(
                filepath,
                resource_type='image',
                fetch_format='auto',
                quality='auto',
            )
            return url
        return cloudinary.CloudinaryImage(filepath).build_url(
            resource_type=resource_type
        )

    return f"/{filepath}"
