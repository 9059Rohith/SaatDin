from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class ApiResponse(BaseModel):
    success: bool = True
    data: Any = None
    message: Optional[str] = None


class OtpRequest(BaseModel):
    phoneNumber: str = Field(min_length=10)


class OtpVerifyRequest(BaseModel):
    phoneNumber: str = Field(min_length=10)
    otp: str = Field(min_length=4, max_length=6)


class RegisterRequest(BaseModel):
    phone: str
    platformName: str
    zone: str
    planName: str
    name: Optional[str] = None


class ZoneOut(BaseModel):
    pincode: str
    name: str
    zoneRiskMultiplier: float
    riskTier: str
    customRainLockThresholdMm3hr: int
    supports: Dict[str, bool]


class PlanOut(BaseModel):
    name: str
    weeklyPremium: int
    perTriggerPayout: int
    maxDaysPerWeek: int
    isPopular: bool = False


class AuthTokenOut(BaseModel):
    token: str
    tokenType: str = "bearer"


class WorkerOut(BaseModel):
    name: str
    phone: str
    platform: str
    zone: str
    zonePincode: str
    plan: str
    policyId: str
    totalEarnings: int = 0
    earningsProtected: int = 0
    isVerified: bool = True
    language: str = "English"


class WorkerStatusOut(BaseModel):
    phone: str
    exists: bool
    worker: Optional[WorkerOut] = None


class TowerCellMetaIn(BaseModel):
    cellId: str = Field(min_length=1, max_length=64)
    radioType: Optional[str] = Field(default=None, max_length=16)
    mcc: Optional[str] = Field(default=None, max_length=8)
    mnc: Optional[str] = Field(default=None, max_length=8)
    tac: Optional[str] = Field(default=None, max_length=32)
    signalDbm: Optional[int] = Field(default=None, ge=-200, le=-1)
    signalLevel: Optional[int] = Field(default=None, ge=0, le=4)
    approxLatitude: Optional[float] = Field(default=None, ge=-90.0, le=90.0)
    approxLongitude: Optional[float] = Field(default=None, ge=-180.0, le=180.0)


class TowerMetadataIn(BaseModel):
    servingCell: Optional[TowerCellMetaIn] = None
    neighborCells: List[TowerCellMetaIn] = Field(default_factory=list, max_length=16)
    networkZoneHintPincode: Optional[str] = Field(default=None, max_length=16)


class MotionMetadataIn(BaseModel):
    windowSeconds: int = Field(ge=1, le=3600)
    sampleCount: int = Field(ge=1, le=1200)
    movingSeconds: Optional[float] = Field(default=None, ge=0.0, le=3600.0)
    stationarySeconds: Optional[float] = Field(default=None, ge=0.0, le=3600.0)
    distanceMeters: Optional[float] = Field(default=None, ge=0.0, le=100000.0)
    avgSpeedMps: Optional[float] = Field(default=None, ge=0.0, le=200.0)
    maxSpeedMps: Optional[float] = Field(default=None, ge=0.0, le=300.0)
    headingChangeRate: Optional[float] = Field(default=None, ge=0.0, le=500.0)


class WorkerLocationSignalRequest(BaseModel):
    latitude: Optional[float] = Field(default=None, ge=-90.0, le=90.0)
    longitude: Optional[float] = Field(default=None, ge=-180.0, le=180.0)
    accuracyMeters: Optional[float] = Field(default=None, ge=0.0, le=5000.0)
    capturedAt: Optional[datetime] = None
    towerMetadata: Optional[TowerMetadataIn] = None
    motionMetadata: Optional[MotionMetadataIn] = None


class TowerValidationOut(BaseModel):
    status: str
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str
    signalPresent: bool
    signalReceivedAt: Optional[str] = None
    signalAgeMinutes: Optional[float] = None


class MotionValidationOut(BaseModel):
    status: str
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str
    eligible: bool
    signalPresent: bool
    signalReceivedAt: Optional[str] = None
    signalAgeMinutes: Optional[float] = None


class LocationSignalValidationOut(BaseModel):
    tower: TowerValidationOut
    motion: MotionValidationOut


class TriggerOut(BaseModel):
    hasActiveAlert: bool
    alertType: str
    alertTitle: str
    alertDescription: str
    confidence: float
    source: str


class TriggerForceRequest(BaseModel):
    zone: str = Field(min_length=2)
    claimType: str = Field(min_length=3)
    alertTitle: str = Field(min_length=3)
    alertDescription: str = Field(min_length=5, max_length=500)
    confidence: float = Field(default=0.9, ge=0.0, le=1.0)


class TriggerForceOut(BaseModel):
    zone: str
    pincode: str
    claimType: str
    alertTitle: str
    hasActiveAlert: bool
    autoClaimsCreated: int
    source: str


class HealthOut(BaseModel):
    status: str
    checks: Dict[str, bool]
    version: str


class PolicyOut(BaseModel):
    status: str
    plan: str
    pendingPlan: Optional[str] = None
    pendingEffectiveDate: Optional[str] = None
    zone: str
    zonePincode: str
    weeklyPremium: int
    earningsProtected: float
    parametricCoverageOn: bool
    perTriggerPayout: int
    maxDaysPerWeek: int
    nextBillingDate: str


class PolicyUpdateRequest(BaseModel):
    planName: str


class ClaimSubmitRequest(BaseModel):
    claimType: str
    description: str = Field(min_length=3, max_length=300)


class ClaimOut(BaseModel):
    id: str
    claimType: str
    status: str
    amount: float
    date: str
    description: str
    source: str
    anomalyScore: Optional[float] = None
    anomalyThreshold: Optional[float] = None
    anomalyFlagged: Optional[bool] = None
    anomalyModelVersion: Optional[str] = None
    anomalyScoredAt: Optional[str] = None
    anomalyFeaturesJson: Optional[Dict[str, Any]] = None
    llmReviewUsed: Optional[bool] = None
    llmReviewStatus: Optional[str] = None
    llmProvider: Optional[str] = None
    llmModel: Optional[str] = None
    llmFallbackUsed: Optional[bool] = None
    llmDecisionConfidence: Optional[float] = None
    llmDecisionJson: Optional[Dict[str, Any]] = None
    llmAttemptsJson: Optional[List[Dict[str, Any]]] = None
    llmValidationError: Optional[str] = None
    llmScoredAt: Optional[str] = None
    towerValidationStatus: Optional[str] = None
    towerZoneConfidence: Optional[float] = None
    towerValidationReason: Optional[str] = None
    towerSignalReceivedAt: Optional[str] = None
    motionValidationStatus: Optional[str] = None
    motionConfidence: Optional[float] = None
    motionValidationReason: Optional[str] = None
    motionSignalReceivedAt: Optional[str] = None


class ZoneLockReportRequest(BaseModel):
    description: str = Field(min_length=5, max_length=500)


class ZoneLockReportOut(BaseModel):
    id: int
    zonePincode: str
    zoneName: str
    description: str
    status: str
    confidence: float
    verifiedCount: int
    createdAt: str


class ZoneLockReportVerifyRequest(BaseModel):
    reportId: int


class ClaimEscalateRequest(BaseModel):
    reason: str = Field(min_length=5, max_length=500)


class ClaimEscalationOut(BaseModel):
    id: int
    claimId: int
    phone: str
    reason: str
    status: str
    reviewNotes: Optional[str] = None
    createdAt: str


class FraudClusterRunOut(BaseModel):
    id: int
    startedAt: str
    finishedAt: Optional[str] = None
    status: str
    errorMessage: Optional[str] = None
    lookbackDays: int
    timeBucketMinutes: int
    minEdgeSupport: int
    mediumRiskThreshold: float
    highRiskThreshold: float
    claimsScanned: int
    edgeCount: int
    clusterCount: int
    flaggedClusterCount: int
    createdAt: str


class FraudClusterSummaryOut(BaseModel):
    id: int
    runId: int
    clusterKey: str
    riskScore: float
    riskLevel: str
    memberCount: int
    edgeCount: int
    eventCount: int
    frequencyScore: float
    recencyScore: float
    supportingMetadataJson: Optional[Dict[str, Any]] = None
    createdAt: str


class FraudClusterMemberOut(BaseModel):
    id: int
    clusterId: int
    phone: str
    claimCount: int
    firstClaimAt: Optional[str] = None
    lastClaimAt: Optional[str] = None
    createdAt: str


class FraudClusterEdgeOut(BaseModel):
    id: int
    clusterId: int
    phoneA: str
    phoneB: str
    coClaimCount: int
    recencyWeight: float
    edgeWeight: float
    lastCoClaimAt: Optional[str] = None
    supportingMetadataJson: Optional[Dict[str, Any]] = None
    createdAt: str


class FraudClusterDetailOut(BaseModel):
    cluster: FraudClusterSummaryOut
    members: List[FraudClusterMemberOut]
    edges: List[FraudClusterEdgeOut]
