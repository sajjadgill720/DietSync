import uuid
from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


class Drug(Base):
    __tablename__ = "drugs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    brand_name = Column(Text, nullable=False)
    drap_reg_no = Column(Text, nullable=True)  # internal only, never exposed via API
    dosage_form = Column(Text, nullable=True)
    company_name = Column(Text, nullable=True)
    resolved_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    # One-to-many relationship with drug_ingredients
    ingredients = relationship("DrugIngredient", back_populates="drug", cascade="all, delete-orphan")

    __table_args__ = (
        Index(
            "idx_drugs_brand_name",
            "brand_name",
            postgresql_using="gin",
            postgresql_ops={"brand_name": "gin_trgm_ops"},
        ),
    )


class DrugIngredient(Base):
    __tablename__ = "drug_ingredients"

    id = Column(Integer, primary_key=True, autoincrement=True)
    drug_id = Column(Integer, ForeignKey("drugs.id", ondelete="CASCADE"), nullable=False)
    generic_name = Column(Text, nullable=False)
    dose = Column(Text, nullable=True)
    rxcui = Column(Text, nullable=True)
    rxnorm_name = Column(Text, nullable=True)

    # Many-to-one relationship with drugs
    drug = relationship("Drug", back_populates="ingredients")

    __table_args__ = (
        Index("idx_drug_ingredients_drug_id", "drug_id"),
        Index("idx_drug_ingredients_rxcui", "rxcui"),
    )


class FDALabel(Base):
    __tablename__ = "fda_labels"

    id = Column(Integer, primary_key=True, autoincrement=True)
    rxcui = Column(Text, nullable=False, unique=True)
    rxnorm_name = Column(Text, nullable=False)
    drug_interactions = Column(Text, nullable=True)
    warnings = Column(Text, nullable=True)
    boxed_warning = Column(Text, nullable=True)
    raw_response = Column(JSONB, nullable=True)
    fetched_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class InteractionJob(Base):
    __tablename__ = "interaction_jobs"

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    drug_a_id = Column(Integer, ForeignKey("drugs.id"), nullable=True)
    drug_b_id = Column(Integer, ForeignKey("drugs.id"), nullable=True)
    status = Column(
        Text,
        nullable=False,
        default="queued",
        server_default=text("'queued'"),
    )
    result = Column(JSONB, nullable=True)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    completed_at = Column(DateTime(timezone=True), nullable=True)

    drug_a = relationship("Drug", foreign_keys=[drug_a_id])
    drug_b = relationship("Drug", foreign_keys=[drug_b_id])

    __table_args__ = (
        CheckConstraint(
            "status IN ('queued', 'processing', 'done', 'failed')",
            name="check_interaction_jobs_status",
        ),
    )


class AllergyClassMap(Base):
    """
    Curated allergy cross-reactivity reference table (PROJECT_SPEC.md lines 205-214).
    Maps patient-facing allergy terms to target cross-reactive RxClass IDs (ATC / MEDRT)
    with cited pharmacology references.
    """
    __tablename__ = "allergy_class_map"

    id = Column(Integer, primary_key=True, autoincrement=True)
    allergy_term = Column(Text, nullable=False)          # patient-facing term, e.g. "penicillin"
    rxclass_id = Column(Text, nullable=False)            # e.g. ATC J01CA (penicillins), J01DB (cephalosporins)
    rxclass_source = Column(Text, nullable=False)        # "ATC" | "MEDRT"
    cross_reactivity_note = Column(Text, nullable=True)  # curated clinical note, cited
    reference = Column(Text, nullable=True)              # source of clinical claim (pharmacology text)

    __table_args__ = (
        Index("idx_allergy_class_map_allergy_term", "allergy_term"),
        Index("idx_allergy_class_map_rxclass_id", "rxclass_id"),
    )
