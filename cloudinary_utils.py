import cloudinary
import cloudinary.uploader
from config import Config

# Initialize Cloudinary
cloudinary.config(
    cloud_name=Config.CLOUDINARY_CLOUD_NAME,
    api_key=Config.CLOUDINARY_API_KEY,
    api_secret=Config.CLOUDINARY_API_SECRET,
    secure=True,
)


def upload_image(file, folder="bike_rental"):
    """
    Upload an image to Cloudinary.

    Args:
        file: File-like object or file path.
        folder: Cloudinary folder to upload into.

    Returns:
        dict with 'url' and 'public_id' keys.
    """
    try:
        result = cloudinary.uploader.upload(
            file,
            folder=folder,
            resource_type="image",
            transformation=[
                {"width": 800, "height": 800, "crop": "limit"},
                {"quality": "auto", "fetch_format": "auto"},
            ],
        )
        return {
            "url": result.get("secure_url"),
            "public_id": result.get("public_id"),
        }
    except Exception as e:
        raise Exception(f"Cloudinary upload failed: {str(e)}")


def delete_image(public_id):
    """Delete an image from Cloudinary by public_id."""
    try:
        result = cloudinary.uploader.destroy(public_id)
        return result.get("result") == "ok"
    except Exception:
        return False
