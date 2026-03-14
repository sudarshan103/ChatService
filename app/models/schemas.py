from pydantic import BaseModel, Field


class MedicalKnowledgeInput(BaseModel):
    """Tool input for semantic medical knowledge search."""

    query: str = Field(description="User symptom or condition text")


class FindDoctorsBySpecialtyInput(BaseModel):
    """Tool input for doctor discovery."""

    specialty: str = Field(description="Medical specialty, e.g. Orthopedics")
    limit: int = Field(default=5, ge=1, le=20, description="Maximum doctors to return")


class ProviderInput(BaseModel):
    """Tool input for provider search in appointment flow."""

    provider_name: str = Field(description="Doctor's name or specialty")


class SlotsInput(BaseModel):
    """Tool input for fetching slots in appointment flow."""

    provider_id: int = Field(description="Doctor's ID from provider search")
    date: str | None = Field(default=None, description="Preferred appointment date text (optional, natural language accepted)")


class SelectSlotInput(BaseModel):
    """Tool input for selecting a numbered slot from prior results."""

    slot_number: int = Field(description="The slot number (1, 2, 3, etc.) that the user selected from the displayed list")
