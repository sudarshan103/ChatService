from pydantic import BaseModel, Field


class KnowledgeSearchInput(BaseModel):
    """Tool input for semantic knowledge base search."""

    query: str = Field(description="User query text (symptom, condition, service need, etc.)")


class FindProvidersByServiceInput(BaseModel):
    """Tool input for provider discovery by service type."""

    specialty: str = Field(description="Service type or area of expertise, e.g. Orthopedics")
    limit: int = Field(default=5, ge=1, le=20, description="Maximum providers to return")


class ProviderInput(BaseModel):
    """Tool input for provider search by name in the appointment flow."""

    provider_name: str = Field(description="Provider's name or service area")


class SlotsInput(BaseModel):
    """Tool input for fetching availability slots in the appointment flow."""

    provider_id: int = Field(description="Provider's ID from a prior provider search")
    date: str | None = Field(default=None, description="Preferred appointment date text (optional, natural language accepted)")


class SelectSlotInput(BaseModel):
    """Tool input for selecting a numbered slot from prior results."""

    slot_number: int = Field(description="The slot number (1, 2, 3, etc.) that the user selected from the displayed list")
