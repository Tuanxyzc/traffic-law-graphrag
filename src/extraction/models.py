"""Pydantic schemas with Controlled Vocabulary for Information Extraction from legal text."""

from __future__ import annotations

import re
import unicodedata
from typing import Literal

from pydantic import BaseModel, Field


def slugify(text: str) -> str:
    """Converts a Vietnamese string into a clean alphanumeric slug for IDs."""
    if not text:
        return ""
    text = text.lower().strip()
    text = text.replace("đ", "d").replace("Đ", "d")
    text = unicodedata.normalize("NFD", text)
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    text = re.sub(r"[^a-z0-9]+", "_", text)
    return text.strip("_")


LegalSubjectSubtype = Literal[
    "VEHICLE_OPERATOR",  # Người điều khiển phương tiện (lái ô tô, lái xe máy, xe đạp)
    "VEHICLE_OWNER",  # Chủ phương tiện (cá nhân hoặc doanh nghiệp)
    "PEDESTRIAN",  # Người đi bộ, dẫn dắt súc vật
    "PASSENGER",  # Người ngồi trên xe, hành khách
    "ORGANIZATION",  # Đơn vị vận tải, trung tâm đăng kiểm, đơn vị thi công
    "AUTHORITY",  # Cơ quan có thẩm quyền xử phạt (CSGT, Thanh tra giao thông)
    "OTHER",
]

VehicleTypeSubtype = Literal[
    "CAR",  # Xe ô tô và các loại xe tương tự xe ô tô
    "MOTORBIKE",  # Xe mô tô, xe gắn máy, xe máy điện
    "TRUCK",  # Xe tải, rơ-moóc, sơ-mi rơ-moóc, container
    "SPECIALIZED_VEHICLE",  # Xe máy chuyên dùng (xe thi công, máy kéo...)
    "NON_MOTORIZED",  # Xe thô sơ, xe đạp, xe súc vật kéo
    "OTHER",
]

RegulatoryObjectSubtype = Literal[
    "TRAFFIC_SIGN",  # Biển báo hiệu đường bộ, vạch kẻ đường, rào chắn
    "TRAFFIC_SIGNAL",  # Đèn tín hiệu giao thông, hiệu lệnh CSGT, còi, đèn ưu tiên
    "LICENSE_DOCUMENT",  # Giấy phép lái xe, đăng ký xe, tem kiểm định, phù hiệu
    "VEHICLE_EQUIPMENT",  # Mũ bảo hiểm, dây an toàn, đèn chiếu sáng, gương, còi
    "CARGO_PASSENGER",  # Hàng hóa chở trên xe, hành khách, hàng nguy hiểm
    "OTHER",
]

ContextConditionSubtype = Literal[
    "LOCATION",  # Đường cao tốc, trong hầm đường bộ, khu đông dân cư, cầu, đường sắt
    "METRIC_THRESHOLD",  # Tốc độ vượt quá, nồng độ cồn, tỷ lệ quá tải, cự ly an toàn
    "TEMPORAL",  # Ban đêm, giờ cao điểm, thời hạn quy định
    "EXCEPTION",  # Ngoại lệ (xe ưu tiên đang làm nhiệm vụ, bất khả kháng)
    "OTHER",
]

SanctionSubtype = Literal[
    "FINE",  # Phạt tiền (kèm chuỗi fine_amount)
    "LICENSE_SUSPENSION",  # Tước quyền sử dụng GPLX, chứng chỉ hành nghề
    "CONFISCATION",  # Tịch thu phương tiện, tang vật vi phạm
    "REMEDIAL",  # Biện pháp khắc phục hậu quả (buộc khôi phục, tháo dỡ)
    "WARNING",  # Phạt cảnh cáo
    "CONSEQUENCE",  # Hậu quả tăng nặng (gây tai nạn, làm chết người, thiệt hại tài sản)
    "OTHER",
]


class LegalSubjectIE(BaseModel):
    """Extracted legal subject who commits or is subject to regulation."""

    name: str = Field(
        ...,
        description="Tên chủ thể (ví dụ: 'Người điều khiển xe ô tô', 'Chủ phương tiện')",
    )
    subtype: LegalSubjectSubtype = Field(
        default="VEHICLE_OPERATOR",
        description="Phân loại chủ thể theo Controlled Vocabulary",
    )

    @property
    def id(self) -> str:
        return f"subj_{slugify(self.name)}"


class VehicleTypeIE(BaseModel):
    """Extracted vehicle type involved in the regulation."""

    name: str = Field(
        ...,
        description="Tên phương tiện (ví dụ: 'Xe ô tô', 'Xe mô tô hai bánh')",
    )
    subtype: VehicleTypeSubtype = Field(
        default="CAR",
        description="Phân loại phương tiện theo Controlled Vocabulary",
    )

    @property
    def id(self) -> str:
        return f"veh_{slugify(self.name)}"


class RegulatoryObjectIE(BaseModel):
    """Extracted regulatory object, equipment, license, or sign involved in the violation."""

    name: str = Field(
        ...,
        description="Tên đối tượng/vật phẩm (ví dụ: 'Đèn tín hiệu giao thông', 'Mũ bảo hiểm', 'Giấy phép lái xe')",
    )
    subtype: RegulatoryObjectSubtype = Field(
        default="TRAFFIC_SIGNAL",
        description="Phân loại đối tượng liên quan theo Controlled Vocabulary",
    )

    @property
    def id(self) -> str:
        return f"obj_{slugify(self.name)}"


class ContextConditionIE(BaseModel):
    """Extracted context condition, location, or metric threshold for the violation."""

    description: str = Field(
        ...,
        description="Mô tả điều kiện/bối cảnh (ví dụ: 'Trên đường cao tốc', 'Chạy quá tốc độ từ 10 đến 20 km/h')",
    )
    subtype: ContextConditionSubtype = Field(
        default="LOCATION",
        description="Phân loại bối cảnh/điều kiện theo Controlled Vocabulary",
    )

    @property
    def id(self) -> str:
        return f"ctx_{slugify(self.description)}"


class SanctionIE(BaseModel):
    """Extracted sanction or penalty applied to a violation."""

    subtype: SanctionSubtype = Field(
        default="FINE",
        description="Loại chế tài hoặc hậu quả tăng nặng theo Controlled Vocabulary",
    )
    description: str = Field(
        ...,
        description="Mô tả chế tài (ví dụ: 'Phạt tiền từ 18.000.000 đồng đến 20.000.000 đồng', 'Tước GPLX từ 01 đến 03 tháng')",
    )
    fine_amount: str | None = Field(
        default=None,
        description="Mức tiền phạt cụ thể nếu có (ví dụ: '18.000.000 - 20.000.000 đồng')",
    )

    @property
    def id_suffix(self) -> str:
        return slugify(self.description)[:30]


ModalityType = Literal[
    "PROHIBITION",  # Hành vi bị cấm, quy tắc vi phạm
    "OBLIGATION",  # Hành vi bắt buộc phải thực hiện/phải có
    "PERMISSION",  # Hành vi được phép, quyền hạn/ngoại lệ cho phép
]

SemanticRelationType = Literal[
    "SUBCLASS_OF",  # Phân cấp chủng loại (Xe ô tô con -> Xe cơ giới)
    "COMPRISES",  # Tập hợp cha bao gồm tập hợp con
    "RELATES_TO",  # Quan hệ ngữ nghĩa chung giữa các thực thể
    "ENFORCED_BY",  # Thẩm quyền xử phạt của cơ quan/chức danh đối với vi phạm/chế tài
]


class SemanticRelationIE(BaseModel):
    """Explicit semantic, taxonomic, or jurisdictional relationship between entities."""

    source_name: str = Field(
        ...,
        description="Tên thực thể nguồn (ví dụ: 'Xe mô tô', 'Trưởng Công an cấp xã')",
    )
    relation: SemanticRelationType = Field(
        ...,
        description="Loại quan hệ: SUBCLASS_OF, COMPRISES, RELATES_TO, ENFORCED_BY",
    )
    target_name: str = Field(
        ...,
        description="Tên thực thể đích (ví dụ: 'Xe hai bánh', 'Phạt tiền đến 2.000.000 đồng')",
    )


class ViolationIE(BaseModel):
    """Extracted specific violation behavior linking to all contextual entities."""

    point_id: str | None = Field(
        default=None,
        description="Mã định danh đơn vị điểm luật tương ứng nếu có (ví dụ: '168_2024_ND-CP_D5_K5_Da')",
    )
    description: str = Field(
        ...,
        description="Mô tả cụ thể hành vi vi phạm (ví dụ: 'Không chấp hành hiệu lệnh của đèn tín hiệu giao thông')",
    )
    modality: ModalityType = Field(
        default="PROHIBITION",
        description="Tính quy phạm: PROHIBITION (cấm/vi phạm), OBLIGATION (bắt buộc), PERMISSION (cho phép)",
    )
    subject_name: str = Field(
        ...,
        description="Tên chủ thể thực hiện hành vi, tương ứng với LegalSubjectIE.name (quan hệ COMMITS)",
    )
    applies_to: list[str] = Field(
        default_factory=list,
        description="Đối tượng hoặc loại xe áp dụng quy định này (quan hệ APPLIES_TO)",
    )
    vehicle_name: str | None = Field(
        default=None,
        description="Tên loại phương tiện gắn liền với hành vi, tương ứng với VehicleTypeIE.name (quan hệ USES_VEHICLE)",
    )
    object_names: list[str] = Field(
        default_factory=list,
        description="Danh sách tên các đối tượng/vật phẩm liên quan (quan hệ INVOLVES_OBJECT)",
    )
    condition_descriptions: list[str] = Field(
        default_factory=list,
        description="Danh sách mô tả các điều kiện/bối cảnh áp dụng (quan hệ UNDER_CONDITION)",
    )
    exception_descriptions: list[str] = Field(
        default_factory=list,
        description="Danh sách mô tả các trường hợp ngoại lệ/miễn trừ (quan hệ HAS_EXCEPTION)",
    )
    cause_descriptions: list[str] = Field(
        default_factory=list,
        description="Danh sách mô tả hậu quả gây ra như tai nạn, hư hại (quan hệ CAUSES)",
    )
    location_descriptions: list[str] = Field(
        default_factory=list,
        description="Danh sách mô tả địa điểm xảy ra vi phạm như cao tốc, cầu vượt (quan hệ LOCATED_AT)",
    )
    sanction_descriptions: list[str] = Field(
        default_factory=list,
        description="Danh sách mô tả các chế tài áp dụng (quan hệ HAS_SANCTION)",
    )
    enforced_by: str | None = Field(
        default=None,
        description="Cơ quan/chức danh có thẩm quyền xử phạt hành vi này nếu có (quan hệ ENFORCED_BY)",
    )


class ClauseExtractionResult(BaseModel):
    """Complete multi-entity extraction result for a grouped legal clause."""

    clause_id: str = Field(
        ...,
        description="Mã định danh của Điều/Khoản (ví dụ: '168_2024_ND-CP_D5_K5')",
    )
    subjects: list[LegalSubjectIE] = Field(
        default_factory=list,
        description="Danh sách các chủ thể vi phạm",
    )
    vehicles: list[VehicleTypeIE] = Field(
        default_factory=list,
        description="Danh sách các loại phương tiện liên quan",
    )
    objects: list[RegulatoryObjectIE] = Field(
        default_factory=list,
        description="Danh sách các đối tượng/biển báo/thiết bị/giấy tờ liên quan",
    )
    conditions: list[ContextConditionIE] = Field(
        default_factory=list,
        description="Danh sách các điều kiện/địa điểm/ngưỡng thông số định khung",
    )
    sanctions: list[SanctionIE] = Field(
        default_factory=list,
        description="Danh sách các chế tài/mức phạt quy định",
    )
    violations: list[ViolationIE] = Field(
        default_factory=list,
        description="Danh sách các hành vi vi phạm cụ thể và mối liên kết của chúng",
    )
    relations: list[SemanticRelationIE] = Field(
        default_factory=list,
        description="Danh sách các quan hệ phân cấp, thẩm quyền hoặc ngữ nghĩa giữa các thực thể",
    )
