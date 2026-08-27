from PIL import Image
from io import BytesIO

def generate_thumbnail(image_path, size=(100, 100)):
    try:
        img = Image.open(image_path)
        img.thumbnail(size)
        buffer = BytesIO()
        img.save(buffer, format="PNG")
        return buffer.getvalue()
    except Exception:
        return None