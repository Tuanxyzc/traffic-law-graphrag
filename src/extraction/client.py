"""Gemini REST API Client with Structured Outputs and automatic key rotation on 429 errors."""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Any

import requests  # type: ignore[import-untyped]

from src.extraction.key_manager import KeyManager
from src.extraction.models import ClauseExtractionResult

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """Bạn là chuyên gia trích xuất đồ thị tri thức pháp lý từ văn bản quy định xử phạt vi phạm giao thông đường bộ Việt Nam.

Nhiệm vụ của bạn:
Phân tích kỹ lưỡng nội dung Điều/Khoản luật giao thông và trích xuất thành cấu trúc JSON theo Controlled Vocabulary:

1. subjects (Chủ thể):
   - name: Tên cụ thể (ví dụ: 'Người điều khiển xe ô tô', 'Chủ phương tiện', 'Người đi bộ').
   - subtype: Chọn 1 trong các giá trị: VEHICLE_OPERATOR, VEHICLE_OWNER, PEDESTRIAN, PASSENGER, ORGANIZATION, AUTHORITY, OTHER.

2. vehicles (Loại phương tiện):
   - name: Tên phương tiện (ví dụ: 'Xe ô tô', 'Xe mô tô, xe gắn máy', 'Xe máy chuyên dùng').
   - subtype: Chọn 1 trong: CAR, MOTORBIKE, TRUCK, SPECIALIZED_VEHICLE, NON_MOTORIZED, OTHER.

3. objects (Đối tượng / Vật phẩm / Thiết bị / Giấy tờ liên quan):
   - name: Tên vật phẩm (ví dụ: 'Đèn tín hiệu giao thông', 'Mũ bảo hiểm', 'Giấy phép lái xe', 'Biển báo cấm').
   - subtype: Chọn 1 trong: TRAFFIC_SIGN, TRAFFIC_SIGNAL, LICENSE_DOCUMENT, VEHICLE_EQUIPMENT, CARGO_PASSENGER, OTHER.

4. conditions (Bối cảnh & Điều kiện áp dụng):
   - description: Tình huống/ngưỡng thông số (ví dụ: 'Trên đường cao tốc', 'Chạy quá tốc độ từ 10 đến 20 km/h', 'Nồng độ cồn vượt quá 0.4 mg/1 lít khí thở').
   - subtype: Chọn 1 trong: LOCATION, METRIC_THRESHOLD, TEMPORAL, EXCEPTION, OTHER.

5. sanctions (Chế tài & Hậu quả):
   - description: Nội dung hình phạt (ví dụ: 'Phạt tiền từ 18.000.000 đồng đến 20.000.000 đồng', 'Tước quyền sử dụng GPLX từ 01 đến 03 tháng', 'Gây tai nạn giao thông').
   - subtype: Chọn 1 trong: FINE, LICENSE_SUSPENSION, CONFISCATION, REMEDIAL, WARNING, CONSEQUENCE, OTHER.
   - fine_amount: Chuỗi số tiền nếu là FINE (ví dụ: '18.000.000 - 20.000.000 đồng').

6. violations (Hành vi vi phạm cụ thể & Quan hệ):
   - point_id: Mã Đơn vị ID được ghi ở đầu mỗi điểm (ví dụ: '168_2024_ND-CP_D5_K5_Da').
   - description: Mô tả hành vi vi phạm rõ ràng, ngắn gọn.
   - modality: Tính quy phạm: 'PROHIBITION' (hành vi cấm/vi phạm), 'OBLIGATION' (hành vi bắt buộc phải làm), 'PERMISSION' (được phép/ngoại lệ). Mặc định là PROHIBITION.
   - subject_name: Tên chủ thể thực hiện hành vi trong danh sách subjects (quan hệ COMMITS).
   - applies_to: Mảng tên chủ thể hoặc loại xe áp dụng quy định (quan hệ APPLIES_TO).
   - vehicle_name: Tên phương tiện tương ứng trong vehicles nếu có (quan hệ USES_VEHICLE).
   - object_names: Mảng tên các objects liên quan (quan hệ INVOLVES_OBJECT).
   - condition_descriptions: Mảng mô tả conditions điều kiện áp dụng (quan hệ UNDER_CONDITION).
   - exception_descriptions: Mảng mô tả các trường hợp ngoại lệ/miễn trừ (quan hệ HAS_EXCEPTION).
   - cause_descriptions: Mảng mô tả hậu quả gây ra như gây tai nạn, thiệt hại (quan hệ CAUSES).
   - location_descriptions: Mảng mô tả địa điểm vi phạm như cao tốc, cầu, hầm (quan hệ LOCATED_AT).
   - sanction_descriptions: Mảng mô tả sanctions áp dụng (quan hệ HAS_SANCTION).
   - enforced_by: Tên cơ quan/chức danh có thẩm quyền xử phạt nếu có (quan hệ ENFORCED_BY).

7. relations (Quan hệ phân loại & ngữ nghĩa giữa các thực thể):
   - source_name: Tên thực thể nguồn.
   - relation: Chọn 1 trong: SUBCLASS_OF (phân cấp cha-con), COMPRISES (bao gồm), RELATES_TO (liên quan đến), ENFORCED_BY (thẩm quyền).
   - target_name: Tên thực thể đích.

LƯU Ý QUAN TRỌNG:
- Chỉ trích xuất thông tin có căn cứ từ văn bản được cung cấp.
- Đảm bảo định dạng JSON hợp lệ tuân thủ schema.
"""

EXTRACTION_JSON_SCHEMA: dict[str, Any] = {
    "type": "OBJECT",
    "properties": {
        "clause_id": {"type": "STRING"},
        "subjects": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "name": {"type": "STRING"},
                    "subtype": {
                        "type": "STRING",
                        "enum": [
                            "VEHICLE_OPERATOR",
                            "VEHICLE_OWNER",
                            "PEDESTRIAN",
                            "PASSENGER",
                            "ORGANIZATION",
                            "AUTHORITY",
                            "OTHER",
                        ],
                    },
                },
                "required": ["name", "subtype"],
            },
        },
        "vehicles": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "name": {"type": "STRING"},
                    "subtype": {
                        "type": "STRING",
                        "enum": [
                            "CAR",
                            "MOTORBIKE",
                            "TRUCK",
                            "SPECIALIZED_VEHICLE",
                            "NON_MOTORIZED",
                            "OTHER",
                        ],
                    },
                },
                "required": ["name", "subtype"],
            },
        },
        "objects": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "name": {"type": "STRING"},
                    "subtype": {
                        "type": "STRING",
                        "enum": [
                            "TRAFFIC_SIGN",
                            "TRAFFIC_SIGNAL",
                            "LICENSE_DOCUMENT",
                            "VEHICLE_EQUIPMENT",
                            "CARGO_PASSENGER",
                            "OTHER",
                        ],
                    },
                },
                "required": ["name", "subtype"],
            },
        },
        "conditions": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "description": {"type": "STRING"},
                    "subtype": {
                        "type": "STRING",
                        "enum": [
                            "LOCATION",
                            "METRIC_THRESHOLD",
                            "TEMPORAL",
                            "EXCEPTION",
                            "OTHER",
                        ],
                    },
                },
                "required": ["description", "subtype"],
            },
        },
        "sanctions": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "description": {"type": "STRING"},
                    "subtype": {
                        "type": "STRING",
                        "enum": [
                            "FINE",
                            "LICENSE_SUSPENSION",
                            "CONFISCATION",
                            "REMEDIAL",
                            "WARNING",
                            "CONSEQUENCE",
                            "OTHER",
                        ],
                    },
                    "fine_amount": {"type": "STRING"},
                },
                "required": ["description", "subtype"],
            },
        },
        "violations": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "point_id": {"type": "STRING"},
                    "description": {"type": "STRING"},
                    "modality": {
                        "type": "STRING",
                        "enum": ["PROHIBITION", "OBLIGATION", "PERMISSION"],
                    },
                    "subject_name": {"type": "STRING"},
                    "applies_to": {
                        "type": "ARRAY",
                        "items": {"type": "STRING"},
                    },
                    "vehicle_name": {"type": "STRING"},
                    "object_names": {
                        "type": "ARRAY",
                        "items": {"type": "STRING"},
                    },
                    "condition_descriptions": {
                        "type": "ARRAY",
                        "items": {"type": "STRING"},
                    },
                    "exception_descriptions": {
                        "type": "ARRAY",
                        "items": {"type": "STRING"},
                    },
                    "cause_descriptions": {
                        "type": "ARRAY",
                        "items": {"type": "STRING"},
                    },
                    "location_descriptions": {
                        "type": "ARRAY",
                        "items": {"type": "STRING"},
                    },
                    "sanction_descriptions": {
                        "type": "ARRAY",
                        "items": {"type": "STRING"},
                    },
                    "enforced_by": {"type": "STRING"},
                },
                "required": [
                    "description",
                    "subject_name",
                    "sanction_descriptions",
                ],
            },
        },
        "relations": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "source_name": {"type": "STRING"},
                    "relation": {
                        "type": "STRING",
                        "enum": [
                            "SUBCLASS_OF",
                            "COMPRISES",
                            "RELATES_TO",
                            "ENFORCED_BY",
                        ],
                    },
                    "target_name": {"type": "STRING"},
                },
                "required": ["source_name", "relation", "target_name"],
            },
        },
    },
    "required": [
        "clause_id",
        "subjects",
        "vehicles",
        "objects",
        "conditions",
        "sanctions",
        "violations",
    ],
}


class GeminiRESTClient:
    """HTTP client communicating with Gemini GenerateContent REST API."""

    def __init__(
        self,
        key_manager: KeyManager | None = None,
        model: str | None = None,
        max_retries: int = 5,
        session: requests.Session | None = None,
    ) -> None:
        self.key_manager = key_manager or KeyManager()
        self.model = model or os.getenv("GEMINI_MODEL", "gemini-3.6-flash")
        self.max_retries = max_retries
        self.session = session or requests.Session()

    def extract_clause(
        self, clause_id: str, prompt_text: str
    ) -> ClauseExtractionResult:
        """Sends grouped clause text to Gemini and parses the structured result."""
        full_user_prompt = (
            f"MÃ ĐIỀU KHOẢN: {clause_id}\n\n"
            f"NỘI DUNG VĂN BẢN CẦN PHÂN TÍCH:\n{prompt_text}\n\n"
            f"Hãy trích xuất subjects, sanctions, và violations cho mã điều khoản '{clause_id}'."
        )

        payload: dict[str, Any] = {
            "system_instruction": {"parts": [{"text": SYSTEM_PROMPT}]},
            "contents": [{"role": "user", "parts": [{"text": full_user_prompt}]}],
            "generationConfig": {
                "responseMimeType": "application/json",
                "responseSchema": EXTRACTION_JSON_SCHEMA,
                "temperature": 0.1,
            },
        }

        retries = 0
        while retries < self.max_retries:
            key = self.key_manager.get_key()
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent?key={key}"

            try:
                resp = self.session.post(
                    url,
                    headers={"Content-Type": "application/json"},
                    json=payload,
                    timeout=60.0,
                )

                # Case 1: Rate limit / Quota reached (HTTP 429)
                if resp.status_code == 429:
                    logger.warning(
                        "Quota exhausted for current key. Rotating to next key in pool..."
                    )
                    self.key_manager.mark_rate_limited(key)
                    retries += 1
                    continue

                # Case 2: Transient server errors (500, 502, 503, 504)
                if resp.status_code in (500, 502, 503, 504):
                    retries += 1
                    logger.warning(
                        "Server error %d from Gemini API. Rotating key with short cooldown and retrying...",
                        resp.status_code,
                    )
                    self.key_manager.mark_server_error(key, cooldown_seconds=15.0)
                    time.sleep(min(retries * 1.5, 6))
                    continue

                # Case 3: Fatal Client Error (400, 403, 404)
                if 400 <= resp.status_code < 500:
                    logger.error(
                        "Fatal client error %d for model '%s': %s",
                        resp.status_code,
                        self.model,
                        resp.text,
                    )
                    resp.raise_for_status()

                resp.raise_for_status()
                data = resp.json()
                candidates = data.get("candidates", [])
                if not candidates:
                    raise ValueError(
                        f"Empty candidate response from Gemini API: {data}"
                    )

                text_content = (
                    candidates[0]
                    .get("content", {})
                    .get("parts", [{}])[0]
                    .get("text", "")
                )
                if not text_content:
                    raise ValueError("No text content returned in candidate part.")

                parsed_json = json.loads(text_content)
                parsed_json["clause_id"] = clause_id
                return ClauseExtractionResult.model_validate(parsed_json)

            except requests.RequestException as req_err:
                retries += 1
                logger.warning(
                    "Network error during Gemini API call: %s. Retry %d/%d",
                    req_err,
                    retries,
                    self.max_retries,
                )
                time.sleep(retries * 2)

        raise RuntimeError(
            f"Failed to extract clause {clause_id} after {self.max_retries} attempts."
        )
