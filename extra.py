import re

def generate_unique_slug(name, model_class):
    # 1. Create base slug
    slug = re.sub(r'[^a-z0-9]+', '-', name.lower()).strip('-')

    # 2. Ensure it's not empty
    if not slug:
        slug = "event"

    # 3. Check uniqueness
    original_slug = slug
    counter = 1

    while model_class.query.filter_by(event_slug=slug).first():
        slug = f"{original_slug}-{counter}"
        counter += 1

    return slug