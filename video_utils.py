import math


def compute_aspect_ratio(width, height):
    if not width or not height:
        return ""
    divisor = math.gcd(width, height)
    return f"{width // divisor}:{height // divisor}"


def compute_orientation(width, height):
    if not width or not height:
        return ""
    if height > width:
        return "vertical"
    elif width > height:
        return "landscape"
    return "square"


def compute_length_category(duration):
    if not duration:
        return ""
    if duration < 60:
        return "short"
    elif duration < 600:
        return "medium"
    elif duration < 3600:
        return "long"
    return "feature"


def format_duration(seconds):
    if not seconds:
        return "0:00"
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def format_filesize(bytes_size):
    if not bytes_size:
        return "0 B"
    for unit in ("B", "KB", "MB", "GB"):
        if bytes_size < 1024:
            return f"{bytes_size:.1f} {unit}"
        bytes_size /= 1024
    return f"{bytes_size:.1f} TB"


def get_directory_size(path):
    import os

    total_size = 0
    if not os.path.exists(path):
        return 0
    for dirpath, _, filenames in os.walk(path):
        for f in filenames:
            fp = os.path.join(dirpath, f)
            if not os.path.islink(fp):
                total_size += os.path.getsize(fp)
    return total_size
