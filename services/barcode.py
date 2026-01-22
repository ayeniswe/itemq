import random
import string

# -----------------------------
# Barcode generation
# -----------------------------

def generate_barcode(length: int = 8) -> str:
    """
    Generate an alphanumeric barcode of fixed length.

    Uses uppercase letters + digits to remain:
    - human-readable
    - case-insensitive in most scanners
    - safe for URLs, filenames, and labels

    Designed to be extended with:
    - collision checks
    - prefixes / namespaces
    - alternate strategies (UUID, GS1, Notion IDs)
    """
    if length < 4:
        raise ValueError("Barcode length too small")

    alphabet = string.ascii_uppercase + string.digits
    return "".join(random.choice(alphabet) for _ in range(length))
