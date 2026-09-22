"""RAGAS LLM-as-a-Judge Engine for GraphRAG Evaluation.

Evaluates:
1. Faithfulness: Are generated claims grounded in retrieved contexts?
2. Answer Relevancy: Does the generated answer address the citizen query?
3. Context Precision: Are relevant contexts ranked higher?
4. Context Recall: Does retrieved context contain all ground-truth statements?
"""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Any

import requests  # type: ignore[import-untyped]

from src.eval.models import EvaluationSample, RagasScore
from src.extraction.key_manager import KeyManager
from src.rag.embedding import EmbeddingManager

logger = logging.getLogger(__name__)

FAITHFULNESS_PROMPT = """Bạn là trọng tài đánh giá trung lập cho hệ thống hỏi đáp pháp luật giao thông.
Nhiệm vụ của bạn là đánh giá tính TRUNG THỰC (Faithfulness) của câu trả lời dựa trên các đoạn ngữ cảnh được cung cấp.

Quy tắc:
1. Tách câu trả lời thành các nhận định/mệnh đề sự thật riêng biệt.
2. Với mỗi nhận định, xác định xem nhận định đó CÓ THỂ ĐƯỢC SUY RA TRỰC TIẾP từ ngữ cảnh hay không.
3. Nếu nhận định không có trong ngữ cảnh hoặc mâu thuẫn với ngữ cảnh, đánh dấu supported = false.
4. Trả về định dạng JSON:
{
  "statements": [
    {"statement": "nội dung nhận định", "supported": true/false, "reason": "giải thích ngắn gọn"}
  ]
}
"""

ANSWER_RELEVANCY_PROMPT = """Bạn là trọng tài đánh giá trung lập cho hệ thống hỏi đáp pháp luật giao thông.
Nhiệm vụ của bạn là phân tích câu trả lời đã sinh và tạo ra 3 câu hỏi giả định tự nhiên mà câu trả lời này giải đáp trọn vẹn nhất.

Quy tắc:
1. Tạo đúng 3 câu hỏi tiếng Việt tự nhiên bám sát nội dung cốt lõi của câu trả lời.
2. Trả về định dạng JSON:
{
  "generated_questions": [
    "Câu hỏi 1",
    "Câu hỏi 2",
    "Câu hỏi 3"
  ]
}
"""

CONTEXT_PRECISION_PROMPT = """Bạn là trọng tài đánh giá trung lập cho hệ thống hỏi đáp pháp luật giao thông.
Nhiệm vụ của bạn là đánh giá xem từng đoạn ngữ cảnh được truy xuất có chứa thông tin hữu ích để trả lời câu hỏi hay không.

Quy tắc:
1. Với từng đoạn ngữ cảnh (theo thứ tự index 1, 2, ...), xác định is_relevant = true nếu đoạn đó cung cấp thông tin liên quan, có ích để giải đáp câu hỏi của người dùng. Ngược lại is_relevant = false.
2. Trả về định dạng JSON:
{
  "contexts_relevance": [
    {"index": 1, "is_relevant": true/false, "reason": "giải thích ngắn"}
  ]
}
"""

CONTEXT_RECALL_PROMPT = """Bạn là trọng tài đánh giá trung lập cho hệ thống hỏi đáp pháp luật giao thông.
Nhiệm vụ của bạn là đánh giá ĐỘ BAO PHỦ (Context Recall) của ngữ cảnh được truy xuất so với câu trả lời chuẩn (Ground Truth).

Quy tắc:
1. Tách câu trả lời chuẩn (Ground Truth) thành các nhận định sự thật quan trọng.
2. Với mỗi nhận định chuẩn, kiểm tra xem nhận định đó CÓ XUẤT HIỆN HOẶC ĐƯỢC SUY RA từ ngữ cảnh được truy xuất hay không (attributed = true/false).
3. Trả về định dạng JSON:
{
  "ground_truth_statements": [
    {"statement": "nội dung nhận định", "attributed": true/false, "reason": "giải thích ngắn"}
  ]
}
"""


def cosine_similarity(vec_a: list[float], vec_b: list[float]) -> float:
    """Calculates cosine similarity between two normalized float vectors."""
    if not vec_a or not vec_b or len(vec_a) != len(vec_b):
        return 0.0
    dot_product = sum(a * b for a, b in zip(vec_a, vec_b))
    return float(max(0.0, min(1.0, dot_product)))


class RagasJudgeClient:
    """LLM-as-a-Judge client using Gemini REST API with key rotation."""

    def __init__(
        self,
        key_manager: KeyManager | None = None,
        model: str | None = None,
        max_retries: int = 4,
        session: requests.Session | None = None,
    ) -> None:
        self.key_manager = key_manager or KeyManager()
        self.model = model or os.getenv("GEMINI_MODEL", "gemini-3.6-flash")
        self.max_retries = max_retries
        self.session = session or requests.Session()

    def generate_json(self, system_prompt: str, user_prompt: str) -> dict[str, Any]:
        """Calls Gemini API requesting JSON output with automatic key rotation."""
        payload: dict[str, Any] = {
            "system_instruction": {"parts": [{"text": system_prompt}]},
            "contents": [{"role": "user", "parts": [{"text": user_prompt}]}],
            "generationConfig": {
                "responseMimeType": "application/json",
                "temperature": 0.0,
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
                    timeout=45.0,
                )

                if resp.status_code == 429:
                    logger.warning("Gemini quota reached in RagasJudge. Rotating key...")
                    self.key_manager.mark_rate_limited(key)
                    retries += 1
                    continue

                if resp.status_code in (500, 502, 503, 504):
                    retries += 1
                    logger.warning(
                        "Server error %d in RagasJudge. Rotating key with short cooldown...",
                        resp.status_code,
                    )
                    self.key_manager.mark_server_error(key, cooldown_seconds=15.0)
                    time.sleep(retries * 1.5)
                    continue

                resp.raise_for_status()
                data = resp.json()
                candidates = data.get("candidates", [])
                if not candidates:
                    raise ValueError(f"Empty candidate response: {data}")

                text = (
                    candidates[0]
                    .get("content", {})
                    .get("parts", [{}])[0]
                    .get("text", "")
                )
                return json.loads(text)  # type: ignore[no-any-return]

            except requests.RequestException as err:
                retries += 1
                logger.warning("Judge API network error: %s (attempt %d)", err, retries)
                time.sleep(retries * 1.5)

        raise RuntimeError(f"RagasJudgeClient failed after {self.max_retries} attempts.")


class RagasJudge:
    """Computes standard RAGAS metrics for an evaluation sample."""

    def __init__(
        self,
        judge_client: RagasJudgeClient | None = None,
        embedding_manager: EmbeddingManager | None = None,
        faithfulness_threshold: float = 0.70,
        relevancy_threshold: float = 0.65,
        context_precision_threshold: float = 0.60,
        context_recall_threshold: float = 0.60,
    ) -> None:
        self.client = judge_client or RagasJudgeClient()
        self.embedding_manager = embedding_manager or EmbeddingManager()
        self.faithfulness_threshold = faithfulness_threshold
        self.relevancy_threshold = relevancy_threshold
        self.context_precision_threshold = context_precision_threshold
        self.context_recall_threshold = context_recall_threshold

    def compute_faithfulness(
        self, generated_answer: str, retrieved_contexts: list[str]
    ) -> float:
        """Measures what fraction of claims in generated answer are supported by contexts."""
        if not generated_answer or not retrieved_contexts:
            return 0.0

        contexts_str = "\n---\n".join(
            f"Đoạn {i+1}:\n{ctx}" for i, ctx in enumerate(retrieved_contexts)
        )
        user_prompt = (
            f"NGỮ CẢNH TRUY XUẤT:\n{contexts_str}\n\n"
            f"CÂU TRẢ LỜI CỦA MÔ HÌNH:\n{generated_answer}"
        )

        res = self.client.generate_json(FAITHFULNESS_PROMPT, user_prompt)
        statements = res.get("statements", [])
        if not statements:
            return 1.0

        supported = sum(1 for s in statements if s.get("supported") is True)
        return round(supported / len(statements), 4)

    def compute_answer_relevancy(
        self, question: str, generated_answer: str
    ) -> float:
        """Measures semantic similarity between user question and synthetic questions from answer."""
        if not question or not generated_answer:
            return 0.0

        user_prompt = f"CÂU TRẢ LỜI CẦN PHÂN TÍCH:\n{generated_answer}"
        res = self.client.generate_json(ANSWER_RELEVANCY_PROMPT, user_prompt)
        gen_questions = res.get("generated_questions", [])
        if not gen_questions:
            return 0.0

        # Embed original question and generated questions
        q_emb = self.embedding_manager.embed_query(question)
        gen_embs = self.embedding_manager.embed_texts(gen_questions)

        similarities = [cosine_similarity(q_emb, g_emb) for g_emb in gen_embs]
        avg_sim = sum(similarities) / len(similarities) if similarities else 0.0
        return round(avg_sim, 4)

    def compute_context_precision(
        self, question: str, retrieved_contexts: list[str]
    ) -> float:
        """Calculates rank-weighted Context Precision@K for retrieved contexts."""
        if not question or not retrieved_contexts:
            return 0.0

        contexts_str = "\n---\n".join(
            f"Đoạn {i+1}:\n{ctx}" for i, ctx in enumerate(retrieved_contexts)
        )
        user_prompt = (
            f"CÂU HỎI:\n{question}\n\n"
            f"CÁC ĐOẠN NGỮ CẢNH ĐƯỢC TRUY XUẤT (THEO THỨ TỰ HẠNG TỪ CAO XUỐNG THẤP):\n{contexts_str}"
        )

        res = self.client.generate_json(CONTEXT_PRECISION_PROMPT, user_prompt)
        relevance_list = res.get("contexts_relevance", [])
        if not relevance_list:
            return 0.0

        # Compute rank-weighted precision: Sum(Precision@k * v_k) / Total_relevant
        num_relevant = 0
        running_relevant = 0
        precision_sum = 0.0

        for rank, item in enumerate(relevance_list, start=1):
            is_rel = bool(item.get("is_relevant", False))
            if is_rel:
                num_relevant += 1
                running_relevant += 1
                precision_at_k = running_relevant / rank
                precision_sum += precision_at_k

        if num_relevant == 0:
            return 0.0

        score = precision_sum / num_relevant
        return round(min(1.0, score), 4)

    def compute_context_recall(
        self, ground_truth: str, retrieved_contexts: list[str]
    ) -> float:
        """Measures fraction of ground-truth statements supported by retrieved contexts."""
        if not ground_truth or not retrieved_contexts:
            return 0.0

        contexts_str = "\n---\n".join(
            f"Đoạn {i+1}:\n{ctx}" for i, ctx in enumerate(retrieved_contexts)
        )
        user_prompt = (
            f"CÂU TRẢ LỜI CHUẨN (GROUND TRUTH):\n{ground_truth}\n\n"
            f"CÁC ĐOẠN NGỮ CẢNH ĐƯỢC TRUY XUẤT:\n{contexts_str}"
        )

        res = self.client.generate_json(CONTEXT_RECALL_PROMPT, user_prompt)
        statements = res.get("ground_truth_statements", [])
        if not statements:
            return 1.0

        attributed = sum(1 for s in statements if s.get("attributed") is True)
        return round(attributed / len(statements), 4)

    def evaluate(
        self,
        sample: EvaluationSample,
        generated_answer: str,
        retrieved_contexts: list[str],
    ) -> RagasScore:
        """Executes full RAGAS evaluation suite for an individual test case."""
        try:
            faithfulness = self.compute_faithfulness(
                generated_answer=generated_answer,
                retrieved_contexts=retrieved_contexts,
            )
            relevancy = self.compute_answer_relevancy(
                question=sample.question,
                generated_answer=generated_answer,
            )
            precision = self.compute_context_precision(
                question=sample.question,
                retrieved_contexts=retrieved_contexts,
            )
            recall = self.compute_context_recall(
                ground_truth=sample.ground_truth_answer,
                retrieved_contexts=retrieved_contexts,
            )

            passed = (
                faithfulness >= self.faithfulness_threshold
                and relevancy >= self.relevancy_threshold
                and precision >= self.context_precision_threshold
                and recall >= self.context_recall_threshold
            )

            return RagasScore(
                faithfulness=faithfulness,
                answer_relevancy=relevancy,
                context_precision=precision,
                context_recall=recall,
                ragas_passed=passed,
                error_message=None,
            )

        except Exception as exc:
            logger.error("Ragas evaluation failed for sample '%s': %s", sample.id, exc)
            return RagasScore(
                faithfulness=None,
                answer_relevancy=None,
                context_precision=None,
                context_recall=None,
                ragas_passed=False,
                error_message=str(exc),
            )
