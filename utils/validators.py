def validate_weapon_data(data):
    errors = []
    if not data.get('weapon_name'):
        errors.append("Weapon Name is required")
    if data.get('range_km') is not None and data['range_km'] < 0:
        errors.append("Range cannot be negative")
    return len(errors) == 0, errors