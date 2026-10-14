"""Comprehensive test suite for Sprint 7 Personal AI Operating System."""

from __future__ import annotations

import io
import json
import sqlite3
import struct
import tarfile
import tempfile
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

# 1. Semantic Memory
from modules.semantic_memory import (
    ContextCompressor,
    DenseEmbeddingProvider,
    HybridSearchEngine,
    HybridSearchResult,
    VectorMemoryStore,
    VectorRecord,
    cosine_similarity,
)

# 2. Knowledge Base
from modules.knowledge_base import (
    Citation,
    CitationFormatter,
    DocxExtractor,
    DocumentExtractResult,
    KnowledgeStore,
    MarkdownExtractor,
    PdfExtractor,
    SemanticChunker,
    TextChunk,
    TextExtractor,
    UniversalExtractor,
)

# 3. Autonomous Learning
from modules.learning import (
    AutomationSuggester,
    AutomationSuggestion,
    BehaviorAnalyzer,
    BehaviorPattern,
    PreferenceLearner,
    UserPreference,
)

# 4. Multi-Channel Connectors
from modules.channels import (
    BaseChannelAdapter,
    ChannelManager,
    ChannelMessage,
    ChannelType,
    DiscordChannelAdapter,
    GmailChannelAdapter,
    RestApiChannelAdapter,
    TelegramChannelAdapter,
    WebhookChannelAdapter,
    WhatsAppChannelAdapter,
)

# 5. Scheduling Intelligence
from modules.scheduling import (
    GoalItem,
    GoalStore,
    HabitItem,
    HabitStore,
    SchedulingIntelligence,
)

# 6. Vision
from modules.vision import (
    UIElement,
    VisionAnalysisResult,
    VisionAnalyzer,
)

# 7. Voice
from modules.voice_system import (
    TextToSpeechEngine,
    VoiceConversationManager,
    VoiceTurnResult,
)

# 8. Plugin System
from modules.plugins import (
    LoadedPlugin,
    PluginLoader,
    PluginManifest,
    PluginPermission,
    PluginSandbox,
    PluginSecurityError,
)

# 9. Observability
from modules.observability import (
    MODEL_PRICING,
    MetricsDashboard,
    TelemetryCollector,
    ToolUsageStats,
)

from modules.memory import MemoryStore


# ============================================================================
# 1. Semantic Memory Tests
# ============================================================================

def test_dense_embedding_provider():
    embedder = DenseEmbeddingProvider(dimension=64)
    v1 = embedder.embed_text("Python autonomous agent")
    v2 = embedder.embed_text("Python autonomous agent")
    v3 = embedder.embed_text("Baking chocolate cake recipes")

    assert len(v1) == 64
    assert v1 == v2  # Deterministic

    sim_same = cosine_similarity(v1, v2)
    sim_diff = cosine_similarity(v1, v3)

    assert sim_same > 0.99
    assert sim_same > sim_diff


def test_vector_memory_store(tmp_path):
    db_file = tmp_path / "test_vec.db"
    store = VectorMemoryStore(db_path=db_file, dimension=64)

    id1 = store.add_vector("Python web development", memory_id=1, metadata={"category": "tech"})
    id2 = store.add_vector("Remote machine learning jobs", memory_id=2, metadata={"category": "jobs"})

    assert id1 > 0
    assert store.count() == 2

    # Search similar
    matches = store.search_similar("Python programming", limit=1)
    assert len(matches) == 1
    assert matches[0]["memory_id"] == 1
    assert matches[0]["score"] > 0.15

    # Delete
    del_count = store.delete_by_memory_id(1)
    assert del_count == 1
    assert store.count() == 1


def test_hybrid_search_engine(tmp_path):
    db_file = tmp_path / "test_hybrid.db"
    mem_store = MemoryStore(db_path=db_file)
    vec_store = VectorMemoryStore(db_path=db_file, dimension=64)

    # Save memory
    item1 = mem_store.save("Python", "Building intelligent AI assistants with Python", category="project")
    vec_store.add_vector(f"{item1.title}\n{item1.content}", memory_id=item1.id)

    item2 = mem_store.save("Meeting", "Team sync on project roadmap and tasks", category="fact")
    vec_store.add_vector(f"{item2.title}\n{item2.content}", memory_id=item2.id)

    engine = HybridSearchEngine(memory_store=mem_store, vector_store=vec_store, k=60)
    results = engine.search("intelligent AI", limit=5)

    assert len(results) >= 1
    assert results[0].memory_id == item1.id
    assert results[0].rrf_score > 0.0


def test_context_compressor():
    compressor = ContextCompressor(max_token_budget=500)
    res = [
        HybridSearchResult(1, "Python", "Aru AI is an autonomous assistant.", "tech", 1, 1, 0.03, 0.9, "both"),
        HybridSearchResult(2, "Rules", "Never leak sensitive secret keys.", "security", 2, 2, 0.02, 0.8, "both"),
    ]
    compressed = compressor.compress_memory_results(res)
    assert "• [TECH] Python:" in compressed
    assert "• [SECURITY] Rules:" in compressed

    # Compress conversation turns
    conv = [
        {"role": "user", "content": "Hello"},
        {"role": "assistant", "content": "Hi Boss! " + "x" * 500},
        {"role": "user", "content": "What is the weather?"},
    ]
    compressed_conv = compressor.compress_conversation_history(conv, max_turns=3)
    assert len(compressed_conv) == 3
    assert "[trimmed]" in compressed_conv[1]["content"]


# ============================================================================
# 2. Knowledge Base Tests
# ============================================================================

def test_document_extractors(tmp_path):
    # 1. Text
    txt_file = tmp_path / "notes.txt"
    txt_file.write_text("Meeting notes from Monday standup.", encoding="utf-8")
    res_txt = TextExtractor().extract(txt_file)
    assert res_txt.doc_type == "text"
    assert "Meeting notes" in res_txt.content

    # 2. Markdown
    md_file = tmp_path / "doc.md"
    md_file.write_text("# Project Roadmap\n\nPhase 1: Ingestion\nPhase 2: RAG", encoding="utf-8")
    res_md = MarkdownExtractor().extract(md_file)
    assert res_md.doc_type == "markdown"
    assert "Project Roadmap" in res_md.headings
    assert "Phase 1" in res_md.content

    # 3. Universal Extractor
    res_u = UniversalExtractor.extract_file(md_file)
    assert res_u.doc_type == "markdown"


def test_semantic_chunker():
    chunker = SemanticChunker(chunk_size=120, chunk_overlap=30)
    text = (
        "Artificial intelligence agents coordinate specialized subtasks. "
        "Each agent runs autonomously on the event bus. "
        "Knowledge retrieval delivers verified source citations to the user. "
        "The system maintains 100% backward compatibility."
    )
    chunks = chunker.chunk_document(text, headings=["Overview"])
    assert len(chunks) >= 2
    for c in chunks:
        assert isinstance(c, TextChunk)
        assert len(c.content) > 0


def test_knowledge_store_ingest_and_search(tmp_path):
    db_file = tmp_path / "test_kb.db"
    store = KnowledgeStore(db_path=db_file, chunk_size=150, chunk_overlap=30)

    doc_file = tmp_path / "ai_agents.txt"
    doc_file.write_text(
        "Aru AI uses an asynchronous AgentEventBus for multi-agent coordination. "
        "Specialized agents include ResearchAgent, MemoryAgent, and TaskAgent.",
        encoding="utf-8",
    )

    ingest_res = store.ingest_file(doc_file)
    assert ingest_res["success"] is True
    assert ingest_res["chunks_count"] >= 1

    docs = store.list_documents()
    assert len(docs) == 1
    assert docs[0]["doc_name"] == "ai_agents.txt"

    # Search citations
    citations = store.search_knowledge("AgentEventBus coordination")
    assert len(citations) >= 1
    assert "AgentEventBus" in citations[0].snippet
    assert citations[0].doc_name == "ai_agents.txt"

    formatted_citation = CitationFormatter.format_citations_block(citations)
    assert "Citations" in formatted_citation
    assert "ai_agents.txt" in formatted_citation


# ============================================================================
# 3. Autonomous Learning Tests
# ============================================================================

def test_preference_learner(tmp_path):
    db_file = tmp_path / "test_pref.db"
    learner = PreferenceLearner(db_path=db_file)

    learner.learn_from_message("Please always reply in English.")
    assert learner.get_preference("language") == "english"

    learner.learn_from_message("Call me Boss.")
    assert learner.get_preference("preferred_name") == "boss"

    learner.learn_from_message("I prefer concise answers.")
    assert learner.get_preference("response_verbosity") == "concise"

    prefs = learner.get_all_preferences()
    assert len(prefs) == 3
    assert "language" in prefs

    profile_text = learner.format_profile()
    assert "english" in profile_text


def test_behavior_analyzer_and_suggester(tmp_path):
    db_file = tmp_path / "test_behavior.db"
    conn = sqlite3.connect(str(db_file))
    conn.execute(
        """
        CREATE TABLE activity_logs (
            id INTEGER PRIMARY KEY,
            category TEXT,
            action TEXT
        );
        """
    )
    # Insert repeat actions
    conn.execute("INSERT INTO activity_logs (category, action) VALUES ('research', 'search');")
    conn.execute("INSERT INTO activity_logs (category, action) VALUES ('research', 'search');")
    conn.execute("INSERT INTO activity_logs (category, action) VALUES ('tasks', 'add');")
    conn.execute("INSERT INTO activity_logs (category, action) VALUES ('tasks', 'add');")
    conn.commit()
    conn.close()

    analyzer = BehaviorAnalyzer(db_path=db_file)
    patterns = analyzer.analyze_patterns(min_frequency=2)
    assert len(patterns) >= 2

    suggester = AutomationSuggester(behavior_analyzer=analyzer, preference_learner=PreferenceLearner(db_path=db_file))
    suggestions = suggester.generate_suggestions()
    assert len(suggestions) >= 1
    assert "workflow" in suggestions[0].recommended_action


# ============================================================================
# 4. Multi-Channel Connectors Tests
# ============================================================================

@pytest.mark.asyncio
async def test_multi_channel_adapters_and_manager():
    mgr = ChannelManager()
    received_inbound: list[ChannelMessage] = []

    async def global_handler(msg: ChannelMessage):
        received_inbound.append(msg)
        return f"Ack: {msg.text}"

    mgr.set_global_message_handler(global_handler)

    # 1. Register adapters
    tg = TelegramChannelAdapter()
    wa = WhatsAppChannelAdapter()
    disc = DiscordChannelAdapter()
    gmail = GmailChannelAdapter()
    rest = RestApiChannelAdapter()
    wh = WebhookChannelAdapter(secret="secret123")

    for adapter in (tg, wa, disc, gmail, rest, wh):
        assert await adapter.connect() is True
        mgr.register_adapter(adapter)

    assert len(mgr.list_channels()) == 6

    # 2. Simulate Inbound WhatsApp Webhook
    wa_payload = {
        "entry": [{
            "changes": [{
                "value": {
                    "messages": [{"from": "+8801700000000", "text": {"body": "Hello Aru via WhatsApp"}}]
                }
            }]
        }]
    }
    reply_wa = await wa.handle_inbound_webhook(wa_payload)
    assert reply_wa == "Ack: Hello Aru via WhatsApp"
    assert len(received_inbound) == 1
    assert received_inbound[0].channel == ChannelType.WHATSAPP

    # 3. Simulate Inbound REST API
    rest_resp = await rest.handle_request({"user_id": "usr_99", "message": "Query via REST"})
    assert rest_resp["success"] is True
    assert rest_resp["response"] == "Ack: Query via REST"

    # 4. Simulate Inbound Webhook with HMAC
    wh_payload = {"sender": "ci_service", "text": "Build passed"}
    wh_raw = json.dumps(wh_payload).encode("utf-8")
    import hmac, hashlib
    valid_sig = "sha256=" + hmac.new(b"secret123", wh_raw, hashlib.sha256).hexdigest()

    wh_res = await wh.handle_inbound_webhook(wh_payload, signature=valid_sig, raw_bytes=wh_raw)
    assert wh_res["success"] is True

    # Invalid HMAC check
    wh_bad = await wh.handle_inbound_webhook(wh_payload, signature="sha256=invalid", raw_bytes=wh_raw)
    assert wh_bad["success"] is False


# ============================================================================
# 5. Scheduling Intelligence Tests
# ============================================================================

def test_habit_store(tmp_path):
    db_file = tmp_path / "test_habits.db"
    store = HabitStore(db_path=db_file)

    store.add_habit("Morning Workout")
    res1 = store.complete_habit("Morning Workout")
    assert res1["streak"] == 1
    assert res1["already_completed"] is False

    # Second completion same day
    res2 = store.complete_habit("Morning Workout")
    assert res2["already_completed"] is True

    habits = store.list_habits()
    assert len(habits) == 1
    assert habits[0].current_streak == 1


def test_goal_store(tmp_path):
    db_file = tmp_path / "test_goals.db"
    store = GoalStore(db_path=db_file)

    gid = store.add_goal("Launch Aru AI OS", description="Sprint 7 release", target_date="2026-10-31", milestones=["Architecture", "Tests"])
    assert gid > 0

    goals = store.list_goals(status="active")
    assert len(goals) == 1
    assert goals[0].title == "Launch Aru AI OS"
    assert len(goals[0].milestones) == 2

    ok = store.update_progress(gid, 100)
    assert ok is True
    assert len(store.list_goals(status="active")) == 0
    assert len(store.list_goals(status="all")) == 1


def test_scheduling_intelligence():
    intel = SchedulingIntelligence()
    briefing = intel.generate_daily_briefing()
    assert "Executive Daily Briefing" in briefing
    assert "Habits" in briefing
    assert "Goals" in briefing

    review = intel.generate_weekly_review()
    assert "Weekly Executive Review" in review

    commitments = intel.detect_commitments("I will submit the complete budget proposal by tomorrow.")
    assert len(commitments) >= 1
    assert "budget proposal" in commitments[0]["action"]


# ============================================================================
# 6. Vision System Tests
# ============================================================================

@pytest.mark.asyncio
async def test_vision_analyzer():
    analyzer = VisionAnalyzer()

    # Synthetic 10x10 PNG image
    png_bytes = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
        + struct.pack(">II", 320, 240)
        + b"\x08\x06\x00\x00\x00\x00\x00\x00\x00IDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
    )

    res = await analyzer.analyze_image(png_bytes)
    assert res.format == "PNG"
    assert res.width == 320
    assert res.height == 240

    screenshot_summary = await analyzer.understand_screenshot(png_bytes)
    assert "Screenshot Analysis" in screenshot_summary
    assert "PNG" in screenshot_summary


# ============================================================================
# 7. Voice System Tests
# ============================================================================

def test_text_to_speech_engine():
    tts = TextToSpeechEngine(sample_rate=8000)
    wav_bytes = tts.synthesize("Hello Boss, Aru is speaking.")

    assert len(wav_bytes) > 44  # WAV header + PCM frames
    assert wav_bytes.startswith(b"RIFF")
    assert b"WAVE" in wav_bytes


@pytest.mark.asyncio
async def test_voice_conversation_manager():
    mock_stt = AsyncMock()
    mock_stt.transcribe.return_value = "What is the schedule today?"
    mock_ai = AsyncMock()
    mock_ai.chat_completion.return_value = "Today you have 3 pending tasks."

    tts = TextToSpeechEngine(sample_rate=8000)
    voice_mgr = VoiceConversationManager(voice_assistant=mock_stt, tts_engine=tts, ai=mock_ai)

    turn = await voice_mgr.process_voice_turn(b"fake_audio_bytes")
    assert turn.success is True
    assert turn.transcript == "What is the schedule today?"
    assert turn.reply_text == "Today you have 3 pending tasks."
    assert len(turn.audio_reply_bytes) > 0


# ============================================================================
# 8. Plugin System Tests
# ============================================================================

def test_plugin_manifest_and_sandbox(tmp_path):
    manifest_data = {
        "name": "calculator_plugin",
        "version": "1.0.0",
        "description": "Calculates math expressions",
        "author": "Aru Team",
        "entrypoint": "plugin.py",
        "permissions": ["read"],
        "tools": ["calc"],
    }
    manifest_file = tmp_path / "manifest.json"
    manifest_file.write_text(json.dumps(manifest_data), encoding="utf-8")

    manifest = PluginManifest.from_file(manifest_file)
    assert manifest.name == "calculator_plugin"
    assert PluginPermission.READ in manifest.permissions

    sandbox = PluginSandbox(manifest)
    # Allowed
    sandbox.check_permission(PluginPermission.READ)

    # Disallowed permission triggers security error
    with pytest.raises(PluginSecurityError) as exc_info:
        sandbox.check_permission(PluginPermission.SHELL)
    assert "SHELL" in str(exc_info.value).upper()


def test_plugin_loader_auto_discovery(tmp_path):
    plugins_dir = tmp_path / "plugins"
    plugins_dir.mkdir()
    plugin1 = plugins_dir / "sample_plugin"
    plugin1.mkdir()

    manifest_data = {
        "name": "sample_plugin",
        "version": "1.0.0",
        "description": "Sample test plugin",
        "author": "Dev",
        "entrypoint": "plugin.py",
        "permissions": ["read"],
    }
    (plugin1 / "manifest.json").write_text(json.dumps(manifest_data), encoding="utf-8")
    (plugin1 / "plugin.py").write_text("def register_tools(sandbox): return []", encoding="utf-8")

    loader = PluginLoader(plugins_dir=plugins_dir)
    loaded = loader.discover_and_load_all()
    assert len(loaded) == 1
    assert loaded[0].manifest.name == "sample_plugin"


# ============================================================================
# 9. Observability Tests
# ============================================================================

def test_telemetry_and_metrics_dashboard(tmp_path):
    db_file = tmp_path / "test_telemetry.db"
    collector = TelemetryCollector(db_path=db_file)

    cost = collector.record_token_usage("qwen/qwen3.8-27b", prompt_tokens=1000, completion_tokens=500)
    assert cost > 0.0

    collector.record_tool_execution("research", duration_sec=0.45, success=True)
    collector.record_tool_execution("research", duration_sec=0.55, success=True)
    collector.record_tool_execution("browser", duration_sec=1.20, success=False)

    summary = collector.get_token_summary()
    assert summary["total_tokens"] == 1500
    assert summary["estimated_cost_usd"] > 0.0

    analytics = collector.get_tool_analytics()
    assert len(analytics) == 2
    assert analytics[0]["tool"] == "research"
    assert analytics[0]["success_rate"] == 100.0

    dashboard = MetricsDashboard(collector)
    md = dashboard.render_markdown()
    assert "Observability Dashboard" in md
    assert "Total Estimated Cost" in md
    assert "research" in md


# ============================================================================
# 10. Deployment Scripts Tests
# ============================================================================

def test_healthcheck_script(tmp_path, monkeypatch):
    from scripts.healthcheck import check_health

    # Test failure when DB missing
    monkeypatch.setattr("scripts.healthcheck.DB_PATH", tmp_path / "nonexistent.db")
    assert check_health() == 1

    # Test pass when DB valid
    valid_db = tmp_path / "healthy.db"
    conn = sqlite3.connect(str(valid_db))
    conn.execute("CREATE TABLE t (id INT);")
    conn.commit()
    conn.close()

    monkeypatch.setattr("scripts.healthcheck.DB_PATH", valid_db)
    assert check_health() == 0


def test_backup_and_restore_script(tmp_path, monkeypatch):
    from scripts.backup_restore import perform_backup, verify_and_restore

    db_file = tmp_path / "memory.db"
    conn = sqlite3.connect(str(db_file))
    conn.execute("PRAGMA journal_mode = WAL;")
    conn.execute("CREATE TABLE test_data (id INTEGER PRIMARY KEY, info TEXT);")
    conn.execute("INSERT INTO test_data (info) VALUES ('critical knowledge');")
    conn.commit()
    conn.close()

    monkeypatch.setattr("scripts.backup_restore.DB_PATH", db_file)
    backup_dir = tmp_path / "backups"

    archive = perform_backup(target_dir=backup_dir)
    assert archive.exists()
    assert archive.suffix == ".gz"

    restore_dir = tmp_path / "restored"
    verified = verify_and_restore(archive, restore_dir=restore_dir)
    assert verified is True

    # Check restored database content
    conn_r = sqlite3.connect(str(restore_dir / "memory.db"))
    row = conn_r.execute("SELECT info FROM test_data WHERE id = 1;").fetchone()
    conn_r.close()
    assert row[0] == "critical knowledge"
