"""
services/allergy_service.py
Root re-export of app.services.allergy_service.
"""

from app.services.allergy_service import allergy_check, is_class_match

__all__ = ["allergy_check", "is_class_match"]
