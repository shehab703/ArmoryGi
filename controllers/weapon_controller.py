class WeaponController:
    def __init__(self, db_manager):
        self.db = db_manager

    def load_weapons(self, filters=None):
        return self.db.get_weapons_paginated(0, 1000, filters=filters)

    def get_weapon(self, weapon_id):
        return self.db.get_weapon_by_id(weapon_id)

    def add_weapon(self, data):
        return self.db.add_weapon(data)

    def delete_weapon(self, weapon_id):
        return self.db.delete_weapon(weapon_id)