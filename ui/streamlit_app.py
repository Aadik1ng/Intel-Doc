"""
Ultra Doc-Intelligence — Streamlit UI
Tabs: Upload | Ask Questions | Structured Extraction
"""
import streamlit as st
import httpx
import json
import time
import sqlite3
import pandas as pd

API_BASE = "http://127.0.0.1:8000"
DB_PATH = "chat_history.db"

# ── Database Initialization ────────────────────────────────────────────────────
def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS chat_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            document_id TEXT,
            timestamp TEXT,
            question TEXT,
            answer TEXT,
            confidence REAL,
            latency_seconds REAL,
            guardrail_triggered BOOLEAN,
            hidden BOOLEAN DEFAULT 0
        )
    ''')
    try:
        c.execute('ALTER TABLE chat_history ADD COLUMN hidden BOOLEAN DEFAULT 0')
    except sqlite3.OperationalError:
        pass

    # New observability columns
    cols = [
        ("model_confidence", "REAL"), ("retrieval_confidence", "REAL"), ("overall_confidence", "REAL"),
        ("confidence_gap", "REAL"), ("retrieval_latency", "REAL"), ("generation_latency", "REAL"),
        ("retrieval_success", "BOOLEAN"), ("context_similarity_mean", "REAL"), ("context_similarity_max", "REAL"),
        ("retrieval_iterations", "INTEGER"), ("answer_relevance", "REAL"), ("faithfulness_score", "REAL"),
        ("context_utilization", "REAL"), ("hallucination_flag", "BOOLEAN"), ("guardrail_type", "TEXT"),
        ("failure_mode", "TEXT"), ("token_input", "INTEGER"), ("token_output", "INTEGER"),
        ("cost", "REAL"), ("query_complexity_score", "REAL"), ("answer_length", "INTEGER")
    ]
    for col_name, col_type in cols:
        try:
            c.execute(f'ALTER TABLE chat_history ADD COLUMN {col_name} {col_type}')
        except sqlite3.OperationalError:
            pass
    
    c.execute('''
        CREATE TABLE IF NOT EXISTS session_summaries (
            document_id TEXT PRIMARY KEY,
            summary TEXT
        )
    ''')
    conn.commit()
    conn.close()

def save_chat(doc_id, ts, question, answer, metrics):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    # Extract metrics into a flat tuple for insertion
    # Ensure they match the order in the INSERT statement
    keys = [
        "document_id", "timestamp", "question", "answer", "overall_confidence",
        "latency_seconds", "guardrail_triggered", "model_confidence", "retrieval_confidence",
        "confidence_gap", "retrieval_latency", "generation_latency", "retrieval_success",
        "context_similarity_mean", "context_similarity_max", "retrieval_iterations",
        "answer_relevance", "faithfulness_score", "context_utilization", "hallucination_flag",
        "guardrail_type", "failure_mode", "token_input", "token_output", "cost",
        "query_complexity_score", "answer_length"
    ]
    
    placeholders = ", ".join(["?"] * len(keys))
    query = f"INSERT INTO chat_history ({', '.join(keys)}) VALUES ({placeholders})"
    
    # Construct values tuple, defaulting to None if missing
    values = [
        doc_id, ts, question, answer, metrics.get("overall_confidence"),
        metrics.get("latency_seconds"), metrics.get("guardrail_triggered"),
        metrics.get("model_confidence"), metrics.get("retrieval_confidence"),
        metrics.get("confidence_gap"), metrics.get("retrieval_latency"),
        metrics.get("generation_latency"), metrics.get("retrieval_success"),
        metrics.get("context_similarity_mean"), metrics.get("context_similarity_max"),
        metrics.get("retrieval_iterations"), metrics.get("answer_relevance"),
        metrics.get("faithfulness_score"), metrics.get("context_utilization"),
        metrics.get("hallucination_flag"), metrics.get("guardrail_type"),
        metrics.get("failure_mode"), metrics.get("token_input"),
        metrics.get("token_output"), metrics.get("cost"),
        metrics.get("query_complexity_score"), metrics.get("answer_length")
    ]
    
    c.execute(query, values)
    conn.commit()
    conn.close()

def get_history(doc_id, include_hidden=False):
    if not doc_id:
        return []
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    if include_hidden:
        c.execute('SELECT * FROM chat_history WHERE document_id = ? ORDER BY id ASC', (doc_id,))
    else:
        c.execute('SELECT * FROM chat_history WHERE document_id = ? AND hidden = 0 ORDER BY id ASC', (doc_id,))
    rows = c.fetchall()
    conn.close()
    return [dict(r) for r in rows]

def clear_chat_history(doc_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('UPDATE chat_history SET hidden = 1 WHERE document_id = ?', (doc_id,))
    conn.commit()
    conn.close()

def get_past_sessions():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute('''
        SELECT 
            c.document_id,
            MIN(c.timestamp) as first_contact,
            (SELECT question FROM chat_history c2 WHERE c2.document_id = c.document_id ORDER BY id ASC LIMIT 1) as first_question,
            s.summary
        FROM chat_history c
        LEFT JOIN session_summaries s ON c.document_id = s.document_id
        GROUP BY c.document_id
        ORDER BY first_contact DESC
    ''')
    rows = c.fetchall()
    conn.close()
    return [dict(r) for r in rows]

def save_session_summary(doc_id, summary):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''
        INSERT OR REPLACE INTO session_summaries (document_id, summary)
        VALUES (?, ?)
    ''', (doc_id, summary))
    conn.commit()
    conn.close()

init_db()

st.set_page_config(
    page_title="Ultra Doc-Intelligence",
    page_icon="🚛",
    layout="wide",
)

if "latest_query_id" not in st.session_state:
    st.session_state["latest_query_id"] = 0

# ── Sidebar ────────────────────────────────────────────────────────────────────
with st.sidebar:
    st.title("🚛 Ultra Doc-Intelligence")
    st.markdown("*Agentic GraphRAG for Logistics Documents*")
    st.divider()
    st.markdown("**Stack**")
    st.markdown("""
- 🔷 **Memgraph 3.0** — Graph + Vector DB
- 🦙 **LlamaIndex** — Knowledge Graph
- 🔗 **LangChain** — Metadata Retrieval
- 🕸️ **LangGraph** — Agentic Loop
- ⚡ **LiteLLM** — LLM Client
- 🗄️ **SQLite** — Local History
""")
    st.divider()
    doc_id = st.text_input("📄 Active Document ID", placeholder="Paste document_id here…")

    st.divider()
    st.markdown("**📂 Past Sessions**")
    
    past_sessions = get_past_sessions()
    if not past_sessions:
        st.info("No past chats recorded yet.")
    else:
        for s in past_sessions:
            d_id = s["document_id"]
            with st.expander(f"📄 {d_id[:8]}..."):
                st.code(d_id, language=None)
                st.markdown(f"**First Query:** _{s['first_question']}_")
                
                if s["summary"]:
                    st.success(f"**LLM Summary:** {s['summary']}")
                else:
                    if st.button("🪄 Summarize with LLM", key=f"sum_{d_id}"):
                        with st.spinner("Asking LLM..."):
                            payload = {
                                "document_id": d_id,
                                "question": "Look at this document and provide a single brief 1-2 sentence summary of what type of document it is and what information it contains.",
                                "filters": None
                            }
                            try:
                                resp = httpx.post(f"{API_BASE}/ask", json=payload, timeout=60.0)
                                if resp.status_code == 200:
                                    ans = resp.json()["answer"]
                                    save_session_summary(d_id, ans)
                                    st.rerun()
                                else:
                                    st.error("Failed to generate summary.")
                            except Exception as e:
                                st.error(f"Error: {e}")

# ── Tabs ───────────────────────────────────────────────────────────────────────
tab_upload, tab_ask, tab_extract, tab_metrics = st.tabs([
    "📤 Upload", 
    "💬 Ask Questions", 
    "📊 Structured Extraction",
    "📈 Session & Metrics"
])

# ═══════════════════════════════════════════════════════════════════════════════
# TAB 1: UPLOAD
# ═══════════════════════════════════════════════════════════════════════════════
with tab_upload:
    st.header("Upload a Logistics Document")
    st.markdown("Supported: **PDF, DOCX, TXT** — Rate Confirmations, BOLs, Invoices, etc.")

    uploaded_file = st.file_uploader("Choose a file", type=["pdf", "docx", "txt"])

    if uploaded_file and st.button("🚀 Upload & Process", type="primary"):
        with st.spinner("Parsing, embedding, and building knowledge graph…"):
            try:
                response = httpx.post(
                    f"{API_BASE}/upload",
                    files={"file": (uploaded_file.name, uploaded_file.getvalue(), uploaded_file.type)},
                    timeout=120.0,
                )
                if response.status_code == 200:
                    data = response.json()
                    st.success("✅ Document processed successfully!")

                    col1, col2, col3, col4 = st.columns(4)
                    col1.metric("Document ID", data["document_id"][:8] + "…")
                    col2.metric("Doc Type", data["doc_type"].replace("_", " ").title())
                    col3.metric("Chunks Created", data["num_chunks"])
                    col4.metric("Entities Found", data["entities_found"])

                    st.info(f"💾 Copy this ID to the sidebar: `{data['document_id']}`")
                    st.code(data["document_id"])
                else:
                    st.error(f"Upload failed: {response.text}")
            except Exception as e:
                st.error(f"Error: {e}")

# ═══════════════════════════════════════════════════════════════════════════════
# TAB 2: ASK QUESTIONS
# ═══════════════════════════════════════════════════════════════════════════════
with tab_ask:
    st.header("Ask Questions About Your Document")

    if not doc_id:
        st.warning("⬅️ Paste a Document ID in the sidebar first.")
    else:
        # Optional metadata filters
        with st.expander("🔍 Advanced Filters (optional)"):
            col_f1, col_f2 = st.columns(2)
            filter_page = col_f1.number_input("Filter by page", min_value=0, value=0, step=1)
            filter_doctype = col_f2.selectbox(
                "Filter by doc type",
                ["(none)", "rate_confirmation", "bol", "invoice", "shipment_instructions", "other"]
            )

        # Show Chat History for this document
        history_records = get_history(doc_id, include_hidden=False)
        if history_records:
            st.divider()
            colA, colB = st.columns([0.8, 0.2])
            colA.subheader(f"💬 Chat History for {doc_id[:8]}...")
            if colB.button("🧹 Clear & Start Fresh", use_container_width=True):
                clear_chat_history(doc_id)
                st.rerun()

            for i, record in enumerate(history_records):
                with st.chat_message("user"):
                    st.write(record["question"])
                with st.chat_message("assistant"):
                    st.write(record["answer"])
                    if record["guardrail_triggered"]:
                        st.caption("⚠️ Guardrail Triggered")
        st.divider()

        col_q, col_btn_ask, col_btn_mic = st.columns([0.7, 0.15, 0.15])
        with col_q:
            question = st.text_input("❓ Your Question", placeholder="What is the carrier rate?", key=f"q_{len(history_records)}", label_visibility="collapsed")
            
        with col_btn_ask:
            ask_pressed = st.button("🔍 Ask", type="primary", use_container_width=True)
            
        audio_data = None
        with col_btn_mic:
            with st.popover("🎤 Voice", use_container_width=True):
                audio_method = st.radio("Method", ["Microphone", "Upload File"], label_visibility="collapsed")
                if audio_method == "Microphone":
                    audio_data = st.audio_input("Speak", label_visibility="collapsed")
                else:
                    audio_data = st.file_uploader("Upload Audio", type=["mp3", "wav", "m4a", "ogg", "webm"], label_visibility="collapsed")
                
                send_audio = st.button("🚀 Send Audio", type="primary", use_container_width=True, disabled=audio_data is None)

        example_qs = ["What is the carrier rate?", "Who is the consignee?", "When is pickup scheduled?",
                      "What is the equipment type?", "Who is the shipper?"]
        st.markdown("**Examples:** " + " | ".join(f"`{q}`" for q in example_qs))

        if (ask_pressed and question) or (send_audio and audio_data):
            filters = {}
            if filter_page > 0:
                filters["source_page"] = int(filter_page)
            if filter_doctype != "(none)":
                filters["doc_type"] = filter_doctype

            # Incremental query ID for state consistency
            st.session_state["latest_query_id"] += 1
            
            with st.spinner("Classifying → Retrieving → Validating → Answering…"):
                import time
                start_t = time.time()
                try:
                    is_audio = send_audio and audio_data is not None
                    
                    if is_audio:
                        files = {"file": (audio_data.name, audio_data.getvalue(), audio_data.type)}
                        data_form = {
                            "document_id": doc_id,
                            "query_id": str(st.session_state["latest_query_id"])
                        }
                        response = httpx.post(f"{API_BASE}/ask_audio", data=data_form, files=files, timeout=60.0)
                        temp_question = "🎤 Processing voice query..."
                    else:
                        payload = {
                            "document_id": doc_id,
                            "question": question,
                            "filters": filters or None,
                            "query_id": str(st.session_state["latest_query_id"])
                        }
                        response = httpx.post(f"{API_BASE}/ask", json=payload, timeout=60.0)
                        temp_question = question
                    
                    latency = time.time() - start_t
                    
                    if response.status_code == 200:
                        data = response.json()
                        
                        # Apply transcript if it came from audio
                        final_question = data.get("transcribed_question") or temp_question
                        
                        # VALIDATE QUERY ID (Alignment with LiveKit logic)
                        incoming_id = int(data.get("query_id") or 0)
                        if incoming_id < st.session_state["latest_query_id"] and incoming_id != 0:
                            st.warning(f"Discarded stale response (ID: {incoming_id})")
                            st.stop()
                        
                        # Add to SQLite database
                        save_chat(
                            doc_id=doc_id,
                            ts=time.strftime("%Y-%m-%d %H:%M:%S"),
                            question=final_question,
                            answer=data["answer"],
                            metrics=data
                        )

                        # Confidence badge
                        conf = data["confidence"]
                        if conf >= 0.7:
                            badge = f"🟢 High Confidence ({conf:.0%})"
                        elif conf >= 0.4:
                            badge = f"🟡 Medium Confidence ({conf:.0%})"
                        else:
                            badge = f"🔴 Low Confidence ({conf:.0%})"

                        if is_audio:
                            st.success(f"**Transcribed:** {final_question}")

                        st.markdown(f"### Answer {badge}")
                        st.markdown(f"> {data['answer']}")

                        if data.get("warning"):
                            st.warning(f"⚠️ {data['warning']}")

                        if data.get("source_texts"):
                            with st.expander(f"📄 Sources ({len(data['source_texts'])} found)"):
                                for i, src in enumerate(data["source_texts"]):
                                    st.markdown(f"**Source {i+1}:**")
                                    st.markdown(f"```\n{src}\n```")

                        # Confidence bar
                        st.progress(min(conf, 1.0), text=f"Confidence: {conf:.0%}")
                    else:
                        st.error(f"Error: {response.text}")
                except Exception as e:
                    st.error(f"Error: {e}")

# ═══════════════════════════════════════════════════════════════════════════════
# TAB 3: STRUCTURED EXTRACTION
# ═══════════════════════════════════════════════════════════════════════════════
with tab_extract:
    st.header("Extract Structured Shipment Data")
    st.markdown("Extracts all 11 shipment fields. Missing fields appear as `null`.")

    if not doc_id:
        st.warning("⬅️ Paste a Document ID in the sidebar first.")
    else:
        if "extract_doc_id" not in st.session_state or st.session_state["extract_doc_id"] != doc_id:
            st.session_state["extract_doc_id"] = doc_id
            st.session_state["extracted_data"] = None

        if st.button("📊 Run Extraction", type="primary"):
            with st.spinner("Extracting structured data with LiteLLM…"):
                try:
                    response = httpx.post(
                        f"{API_BASE}/extract",
                        json={"document_id": doc_id},
                        timeout=60.0,
                    )
                    if response.status_code == 200:
                        data = response.json()
                        st.session_state["extracted_data"] = data["shipment_data"]
                    else:
                        st.error(f"Error: {response.text}")
                except Exception as e:
                    st.error(f"Error: {e}")
        
        if st.session_state["extracted_data"]:
            shipment = st.session_state["extracted_data"]
            st.success("✅ Extraction complete")

            # Display as a nice table
            field_labels = {
                "shipment_id": "Shipment ID",
                "shipper": "Shipper",
                "consignee": "Consignee",
                "pickup_datetime": "Pickup Date/Time",
                "delivery_datetime": "Delivery Date/Time",
                "equipment_type": "Equipment Type",
                "mode": "Mode",
                "rate": "Rate",
                "currency": "Currency",
                "weight": "Weight",
                "carrier_name": "Carrier Name",
            }

            rows = []
            for field, label in field_labels.items():
                value = shipment.get(field)
                rows.append({
                    "Field": label,
                    "Value": value if value is not None else "—",
                    "Found": "✅" if value else "❌"
                })

            st.dataframe(rows, use_container_width=True, hide_index=True)

            # Raw JSON
            with st.expander("🔧 Raw JSON"):
                st.json(shipment)

# ═══════════════════════════════════════════════════════════════════════════════
# TAB 4: SESSION & METRICS
# ═══════════════════════════════════════════════════════════════════════════════
with tab_metrics:
    st.header("📈 Session Diagnostics & RAG Metrics")
    st.markdown("Monitor real-time system metrics, latency, and proxy-confidence securely tied to your active document.")
    
    if not doc_id:
        st.warning("⬅️ Paste a Document ID in the sidebar first to view metrics.")
    else:
        history = get_history(doc_id, include_hidden=True)
        
        if not history:
            st.info(f"No queries have been asked for document `{doc_id}` yet. Go to 'Ask Questions' to generate metrics.")
        else:
            # Calculate production RAG metrics
            total_queries = len(history)
            df = pd.DataFrame(history)
            # Handle legacy rows with nulls
            df = df.fillna(0)
            
            # 1. Performance Row
            st.subheader("⚡ System Performance")
            p_col1, p_col2, p_col3, p_col4 = st.columns(4)
            avg_lat = df["latency_seconds"].mean()
            p95_lat = df["latency_seconds"].quantile(0.95)
            p_col1.metric("Avg Latency", f"{avg_lat:.2f}s")
            p_col2.metric("P95 Latency", f"{p95_lat:.2f}s")
            p_col3.metric("Throughput", f"{total_queries / (max(len(df), 1)):.1f} q/sess")
            p_col4.metric("Avg Gen Latency", f"{df['generation_latency'].mean():.2f}s")

            st.divider()
            
            # 2. Retrieval & Reliability Row
            st.subheader("🎯 Retrieval & Reliability")
            r_col1, r_col2, r_col3, r_col4 = st.columns(4)
            r_col1.metric("Avg Faithfulness", f"{df['faithfulness_score'].mean()*100:.1f}%")
            r_col2.metric("Avg Relevance", f"{df['answer_relevance'].mean()*100:.1f}%")
            r_col3.metric("Max Similarity", f"{df['context_similarity_max'].mean():.3f}")
            r_col4.metric("Hallucination Rate", f"{(df['hallucination_flag'].sum()/total_queries)*100:.1f}%", delta_color="inverse")

            st.divider()

            # 3. Usage & Economics Row
            st.subheader("💰 Usage & Economics")
            e_col1, e_col2, e_col3, e_col4 = st.columns(4)
            total_cost = df["cost"].sum()
            avg_tokens = df["token_input"].mean() + df["token_output"].mean()
            e_col1.metric("Total Session Cost", f"${total_cost:.4f}")
            e_col2.metric("Avg Tokens/Query", f"{int(avg_tokens if not pd.isna(avg_tokens) else 0)}")
            e_col3.metric("Context Utilization", f"{df['context_utilization'].mean()*100:.1f}%")
            e_col4.metric("Avg Complexity", f"{df['query_complexity_score'].mean():.2f}")

            st.divider()
            st.subheader("📋 Master Observability Log")
            
            # Display full log with relevant columns
            view_cols = [
                'timestamp', 'question', 'answer', 'overall_confidence', 'faithfulness_score',
                'answer_relevance', 'hallucination_flag', 'latency_seconds', 'retrieval_iterations',
                'token_input', 'token_output', 'cost', 'failure_mode'
            ]
            st.dataframe(df[view_cols], use_container_width=True, hide_index=True)
            
            # Export everything
            csv = df.to_csv(index=False).encode('utf-8')
            st.download_button(
                label="💾 Export Full Observability Data (CSV)",
                data=csv,
                file_name=f"ultra_rag_metrics_{doc_id}.csv",
                mime="text/csv",
            )
