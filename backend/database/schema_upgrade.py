"""Idempotent runtime database schema upgrades for CookMate."""

from __future__ import annotations

import logging
from typing import Any

from backend.database.connection import fetch_all, transaction

logger = logging.getLogger(__name__)

_CHATBOT_KNOWLEDGE_BASE_DDL = """
CREATE TABLE IF NOT EXISTS chatbot_knowledge_base (
  kb_id INT NOT NULL AUTO_INCREMENT,
  topic VARCHAR(120) NOT NULL DEFAULT 'general',
  category VARCHAR(120) NOT NULL DEFAULT 'cooking_tip',
  title VARCHAR(255) NOT NULL,
  keywords_text TEXT NOT NULL,
  content TEXT NOT NULL,
  substitution_json JSON NULL,
  is_active BOOLEAN NOT NULL DEFAULT TRUE,
  priority INT NOT NULL DEFAULT 10,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (kb_id),
  UNIQUE KEY uq_chatbot_kb_title (title(191)),
  KEY ix_chatbot_kb_topic (topic, is_active, priority)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
"""

_CHATBOT_SYNONYMS_DDL = """
CREATE TABLE IF NOT EXISTS chatbot_synonyms (
  synonym_id INT NOT NULL AUTO_INCREMENT,
  canonical_term VARCHAR(150) NOT NULL,
  variant_term VARCHAR(150) NOT NULL,
  region VARCHAR(60) NOT NULL DEFAULT 'toan_quoc',
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (synonym_id),
  UNIQUE KEY uq_chatbot_synonym_pair (canonical_term(90), variant_term(90)),
  KEY ix_chatbot_synonym_variant (variant_term(90))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
"""

_CHATBOT_LEARNED_QA_DDL = """
CREATE TABLE IF NOT EXISTS chatbot_learned_qa (
  qa_id INT NOT NULL AUTO_INCREMENT,
  normalized_question VARCHAR(255) NOT NULL,
  question_text TEXT NOT NULL,
  intent VARCHAR(80) NOT NULL DEFAULT 'cooking',
  answer_text MEDIUMTEXT NOT NULL,
  keywords_text TEXT NOT NULL,
  matched_recipe_ids VARCHAR(255) NULL DEFAULT NULL,
  model_used VARCHAR(120) NOT NULL DEFAULT '',
  quality_score DECIMAL(5,2) NOT NULL DEFAULT 0.70,
  usage_count INT NOT NULL DEFAULT 1,
  is_verified BOOLEAN NOT NULL DEFAULT FALSE,
  source_type ENUM('CURATED','AUTO_LEARNED','GEMINI_VERIFIED') NOT NULL DEFAULT 'AUTO_LEARNED',
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (qa_id),
  UNIQUE KEY uq_chatbot_learned_question (normalized_question(191)),
  KEY ix_chatbot_learned_quality (is_verified, quality_score, usage_count)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
"""


def _existing_columns(table_name: str) -> set[str]:
    rows = fetch_all(
        "SELECT COLUMN_NAME AS name FROM information_schema.COLUMNS "
        "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s",
        (table_name,),
    )
    return {str(row.get("name") or "").lower() for row in rows}


def ensure_runtime_schema() -> dict[str, Any]:
    """Safely ensure new columns and chatbot memory tables exist without dropping data."""
    changes: list[str] = []
    cat_cols = _existing_columns("categories")
    rec_cols = _existing_columns("recipes")

    with transaction() as (_, cur):
        if "recipe_count" not in cat_cols:
            cur.execute("ALTER TABLE categories ADD COLUMN recipe_count INT NOT NULL DEFAULT 0")
            changes.append("categories.recipe_count")
        if "rejection_reason" not in rec_cols:
            cur.execute("ALTER TABLE recipes ADD COLUMN rejection_reason VARCHAR(500) NULL DEFAULT NULL AFTER status")
            changes.append("recipes.rejection_reason")
        cur.execute(_CHATBOT_KNOWLEDGE_BASE_DDL)
        cur.execute(_CHATBOT_SYNONYMS_DDL)
        cur.execute(_CHATBOT_LEARNED_QA_DDL)
        qa_cols = _existing_columns("chatbot_learned_qa")
        if "matched_recipe_ids" not in qa_cols:
            cur.execute("ALTER TABLE chatbot_learned_qa ADD COLUMN matched_recipe_ids VARCHAR(255) NULL DEFAULT NULL AFTER keywords_text")
            changes.append("chatbot_learned_qa.matched_recipe_ids")
        cur.execute(
            "DELETE FROM chatbot_learned_qa WHERE answer_text LIKE '%chưa có trong CSDL%' "
            "OR answer_text LIKE '%Gợi ý tự nấu%' OR answer_text LIKE '%tự nấu do%'"
        )
        cur.execute(
            "UPDATE categories c SET recipe_count = ("
            "SELECT COUNT(*) FROM recipes r WHERE r.category_id = c.category_id AND r.status = 'APPROVED'"
            ")"
        )
    if changes:
        logger.info("[SCHEMA] Applied runtime schema upgrades: %s", ",".join(changes))
    return {"ok": True, "added_columns": changes}
