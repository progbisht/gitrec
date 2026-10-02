import os
import json
from flask import Flask, render_template_string, request, jsonify
from gitrec.storage.db import Storage
from gitrec.models.base import WorkType, WorkItemStatus, KanbanStatus, WorkItemModel

def create_app(db_path: str = "gitrec_store.db") -> Flask:
    app = Flask(__name__)
    storage = Storage(db_path)

    HTML_TEMPLATE = """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>GitRec - Jira Kanban Backfill Studio</title>
        <link rel="preconnect" href="https://fonts.googleapis.com">
        <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
        <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;500;600&display=swap" rel="stylesheet">
        <style>
            :root {
                --bg-main: #0b0f19;
                --bg-card: rgba(18, 24, 38, 0.75);
                --bg-card-hover: rgba(26, 35, 54, 0.9);
                --border-color: rgba(255, 255, 255, 0.08);
                --border-focus: #3b82f6;
                --text-main: #f3f4f6;
                --text-muted: #9ca3af;
                --primary: #3b82f6;
                --primary-glow: rgba(59, 130, 246, 0.25);
                --success: #10b981;
                --warning: #f59e0b;
                --danger: #ef4444;
                --purple: #8b5cf6;
            }

            * {
                box-sizing: border-box;
                margin: 0;
                padding: 0;
            }

            body {
                font-family: 'Plus Jakarta Sans', sans-serif;
                background-color: var(--bg-main);
                color: var(--text-main);
                min-height: 100vh;
                padding: 2rem;
                background-image: 
                    radial-gradient(at 0% 0%, rgba(59, 130, 246, 0.12) 0px, transparent 50%),
                    radial-gradient(at 100% 100%, rgba(139, 92, 246, 0.12) 0px, transparent 50%);
                background-attachment: fixed;
            }

            .container {
                max-width: 1400px;
                margin: 0 auto;
            }

            header {
                display: flex;
                justify-content: space-between;
                align-items: center;
                margin-bottom: 2rem;
                padding-bottom: 1.5rem;
                border-bottom: 1px solid var(--border-color);
                flex-wrap: wrap;
                gap: 1rem;
            }

            .logo-area h1 {
                font-size: 1.8rem;
                font-weight: 800;
                background: linear-gradient(135deg, #60a5fa, #c084fc);
                -webkit-background-clip: text;
                -webkit-text-fill-color: transparent;
                display: flex;
                align-items: center;
                gap: 0.5rem;
            }

            .stats-bar {
                display: flex;
                gap: 1rem;
                flex-wrap: wrap;
            }

            .stat-badge {
                background: var(--bg-card);
                border: 1px solid var(--border-color);
                border-radius: 12px;
                padding: 0.5rem 1rem;
                display: flex;
                flex-direction: column;
                align-items: center;
                backdrop-filter: blur(10px);
            }

            .stat-badge .val {
                font-size: 1.25rem;
                font-weight: 700;
                color: #60a5fa;
            }

            .stat-badge .label {
                font-size: 0.75rem;
                color: var(--text-muted);
                text-transform: uppercase;
                letter-spacing: 0.05em;
            }

            .grid {
                display: grid;
                grid-template-columns: 1fr;
                gap: 1.25rem;
            }

            .card {
                background: var(--bg-card);
                border: 1px solid var(--border-color);
                border-radius: 16px;
                padding: 1.5rem;
                backdrop-filter: blur(12px);
                transition: all 0.2s ease;
            }

            .card:hover {
                border-color: rgba(96, 165, 250, 0.4);
                box-shadow: 0 10px 25px -5px rgba(0, 0, 0, 0.3);
            }

            .card-header {
                display: flex;
                justify-content: space-between;
                align-items: flex-start;
                gap: 1rem;
                margin-bottom: 1rem;
            }

            .card-title-area {
                flex-grow: 1;
            }

            .card-id {
                font-family: 'JetBrains Mono', monospace;
                font-size: 0.85rem;
                font-weight: 600;
                background: rgba(59, 130, 246, 0.2);
                color: #93c5fd;
                padding: 0.2rem 0.6rem;
                border-radius: 6px;
                display: inline-block;
                margin-bottom: 0.4rem;
            }

            .card-title {
                font-size: 1.2rem;
                font-weight: 700;
                color: #fff;
            }

            .badge {
                font-size: 0.75rem;
                font-weight: 600;
                padding: 0.3rem 0.75rem;
                border-radius: 20px;
                text-transform: uppercase;
                letter-spacing: 0.04em;
            }

            .badge-high { background: rgba(16, 185, 129, 0.2); color: #34d399; border: 1px solid rgba(16, 185, 129, 0.4); }
            .badge-med { background: rgba(245, 158, 11, 0.2); color: #fbbf24; border: 1px solid rgba(245, 158, 11, 0.4); }
            .badge-low { background: rgba(239, 68, 68, 0.2); color: #f87171; border: 1px solid rgba(239, 68, 68, 0.4); }

            .badge-kanban-done { background: rgba(16, 185, 129, 0.2); color: #34d399; border: 1px solid rgba(16, 185, 129, 0.5); }
            .badge-kanban-progress { background: rgba(59, 130, 246, 0.25); color: #60a5fa; border: 1px solid rgba(59, 130, 246, 0.5); }
            .badge-kanban-ready { background: rgba(139, 92, 246, 0.25); color: #c084fc; border: 1px solid rgba(139, 92, 246, 0.5); }
            .badge-kanban-backlog { background: rgba(100, 116, 139, 0.25); color: #cbd5e1; border: 1px solid rgba(100, 116, 139, 0.5); }

            .card-body {
                display: grid;
                grid-template-columns: 2fr 1fr;
                gap: 1.5rem;
            }

            .meta-section {
                display: flex;
                flex-direction: column;
                gap: 0.75rem;
            }

            .meta-row {
                font-size: 0.875rem;
                color: var(--text-muted);
                display: flex;
                gap: 0.5rem;
                flex-wrap: wrap;
                align-items: center;
            }

            .meta-tag {
                background: rgba(255, 255, 255, 0.05);
                padding: 0.2rem 0.5rem;
                border-radius: 4px;
                font-family: 'JetBrains Mono', monospace;
                font-size: 0.8rem;
                color: #d1d5db;
            }

            .evidence-box {
                background: rgba(0, 0, 0, 0.3);
                border: 1px dashed rgba(255, 255, 255, 0.1);
                border-radius: 8px;
                padding: 0.75rem;
                font-size: 0.8rem;
                color: #94a3b8;
            }

            .evidence-box ul {
                list-style-type: none;
                margin-top: 0.25rem;
            }

            .evidence-box li::before {
                content: "•";
                color: #60a5fa;
                margin-right: 0.5rem;
            }

            .actions-section {
                display: flex;
                flex-direction: column;
                gap: 0.75rem;
                border-left: 1px solid var(--border-color);
                padding-left: 1.5rem;
            }

            select, input[type="text"] {
                background: rgba(15, 23, 42, 0.8);
                border: 1px solid var(--border-color);
                color: #fff;
                padding: 0.6rem 0.8rem;
                border-radius: 8px;
                font-size: 0.875rem;
                outline: none;
                width: 100%;
            }

            select:focus, input[type="text"]:focus {
                border-color: var(--border-focus);
                box-shadow: 0 0 0 2px var(--primary-glow);
            }

            .btn {
                background: var(--primary);
                color: #fff;
                border: none;
                padding: 0.6rem 1rem;
                border-radius: 8px;
                font-weight: 600;
                font-size: 0.875rem;
                cursor: pointer;
                transition: all 0.15s ease;
                display: inline-flex;
                align-items: center;
                justify-content: center;
                gap: 0.5rem;
            }

            .btn:hover {
                background: #2563eb;
            }

            .btn-success { background: #059669; }
            .btn-success:hover { background: #047857; }
            .btn-danger { background: #dc2626; }
            .btn-danger:hover { background: #b91c1c; }

            .toast {
                position: fixed;
                bottom: 2rem;
                right: 2rem;
                background: #1e293b;
                border: 1px solid #3b82f6;
                padding: 1rem 1.5rem;
                border-radius: 10px;
                color: #fff;
                box-shadow: 0 10px 30px rgba(0, 0, 0, 0.5);
                display: none;
                z-index: 100;
            }
        </style>
    </head>
    <body>
        <div class="container">
            <header>
                <div class="logo-area">
                    <h1>🚀 GitRec Kanban Studio</h1>
                </div>
                <div class="stats-bar">
                    <div class="stat-badge">
                        <span class="val">{{ items|length }}</span>
                        <span class="label">Total Items</span>
                    </div>
                    <div class="stat-badge">
                        <span class="val" style="color: #cbd5e1;">{{ backlog_count }}</span>
                        <span class="label">Backlog</span>
                    </div>
                    <div class="stat-badge">
                        <span class="val" style="color: #c084fc;">{{ ready_count }}</span>
                        <span class="label">Ready For Dev</span>
                    </div>
                    <div class="stat-badge">
                        <span class="val" style="color: #60a5fa;">{{ progress_count }}</span>
                        <span class="label">In Progress</span>
                    </div>
                    <div class="stat-badge">
                        <span class="val" style="color: #34d399;">{{ done_count }}</span>
                        <span class="label">Done</span>
                    </div>
                </div>
            </header>

            <div class="grid">
                {% for item in items %}
                <div class="card" id="card-{{ item.id }}">
                    <div class="card-header">
                        <div class="card-title-area">
                            <span class="card-id">{{ item.id }}</span>
                            <input type="text" id="title-{{ item.id }}" value="{{ item.title }}" style="font-weight: 700; font-size: 1.1rem; margin-top: 0.25rem;">
                        </div>
                        <div style="display: flex; gap: 0.5rem; flex-wrap: wrap;">
                            {% if item.kanban_status.value == 'Done' %}
                            <span class="badge badge-kanban-done">Done</span>
                            {% elif item.kanban_status.value == 'In Progress' %}
                            <span class="badge badge-kanban-progress">In Progress</span>
                            {% elif item.kanban_status.value == 'Ready For Development' %}
                            <span class="badge badge-kanban-ready">Ready For Dev</span>
                            {% else %}
                            <span class="badge badge-kanban-backlog">Backlog</span>
                            {% endif %}

                            {% if item.confidence >= 0.90 %}
                            <span class="badge badge-high">{{ '%.2f'|format(item.confidence) }} Conf</span>
                            {% elif item.confidence >= 0.70 %}
                            <span class="badge badge-med">{{ '%.2f'|format(item.confidence) }} Conf</span>
                            {% else %}
                            <span class="badge badge-low">{{ '%.2f'|format(item.confidence) }} Needs Review</span>
                            {% endif %}
                        </div>
                    </div>

                    <div class="card-body">
                        <div class="meta-section">
                            <div class="meta-row">
                                <strong>Authors:</strong> {{ item.authors|join(', ') or 'None' }}
                                &bull; <strong>Activity:</strong> {{ item.first_activity.strftime('%Y-%m-%d') }} to {{ item.last_activity.strftime('%Y-%m-%d') }}
                            </div>
                            
                            {% if item.parent_id %}
                            <div class="meta-row">
                                <strong>Parent Ticket:</strong>
                                <span class="meta-tag" style="background: rgba(139, 92, 246, 0.3); color: #c084fc;">Parent: {{ item.parent_id }}</span>
                            </div>
                            {% endif %}

                            {% if item.children_ids %}
                            <div class="meta-row">
                                <strong>Sub-tasks ({{ item.children_ids|length }}):</strong>
                                {% for cid in item.children_ids %}
                                    <span class="meta-tag" style="background: rgba(59, 130, 246, 0.2); color: #93c5fd;">{{ cid }}</span>
                                {% endfor %}
                            </div>
                            {% endif %}

                            <div class="meta-row">
                                <strong>Linked:</strong>
                                {% if item.pr_numbers %}
                                    {% for pr in item.pr_numbers %}<span class="meta-tag">PR #{{ pr }}</span>{% endfor %}
                                {% endif %}
                                {% if item.issue_numbers %}
                                    {% for iss in item.issue_numbers %}<span class="meta-tag">Issue #{{ iss }}</span>{% endfor %}
                                {% endif %}
                                <span class="meta-tag">{{ item.commit_shas|length }} Commits</span>
                            </div>

                            <div class="meta-row">
                                <strong>Modules:</strong> {{ item.affected_modules|join(', ') or 'root' }}
                            </div>

                            <div class="evidence-box">
                                <strong>Evidence & Reasoning:</strong>
                                <ul>
                                    {% for ev in item.evidence %}
                                    <li>{{ ev }}</li>
                                    {% endfor %}
                                </ul>
                            </div>
                        </div>

                        <div class="actions-section">
                            <div>
                                <label style="font-size: 0.75rem; color: var(--text-muted); text-transform: uppercase;">Kanban Status</label>
                                <select id="kanban-{{ item.id }}">
                                    {% for ks in kanban_statuses %}
                                    <option value="{{ ks.value }}" {% if item.kanban_status.value == ks.value %}selected{% endif %}>{{ ks.value }}</option>
                                    {% endfor %}
                                </select>
                            </div>

                            <div>
                                <label style="font-size: 0.75rem; color: var(--text-muted); text-transform: uppercase;">Classification</label>
                                <select id="type-{{ item.id }}">
                                    {% for wt in work_types %}
                                    <option value="{{ wt.value }}" {% if item.work_type.value == wt.value %}selected{% endif %}>{{ wt.value }}</option>
                                    {% endfor %}
                                </select>
                            </div>

                            <div>
                                <label style="font-size: 0.75rem; color: var(--text-muted); text-transform: uppercase;">Review Status</label>
                                <select id="status-{{ item.id }}">
                                    {% for st in statuses %}
                                    <option value="{{ st.value }}" {% if item.status.value == st.value %}selected{% endif %}>{{ st.value }}</option>
                                    {% endfor %}
                                </select>
                            </div>

                            <button class="btn btn-success" onclick="saveItem('{{ item.id }}')">
                                Save Changes
                            </button>
                        </div>
                    </div>
                </div>
                {% endfor %}
            </div>
        </div>

        <div class="toast" id="toast">Changes saved successfully!</div>

        <script>
            function showToast(msg) {
                const t = document.getElementById('toast');
                t.innerText = msg;
                t.style.display = 'block';
                setTimeout(() => { t.style.display = 'none'; }, 2500);
            }

            async function saveItem(itemId) {
                const title = document.getElementById(`title-${itemId}`).value;
                const workType = document.getElementById(`type-${itemId}`).value;
                const status = document.getElementById(`status-${itemId}`).value;
                const kanbanStatus = document.getElementById(`kanban-${itemId}`).value;

                const resp = await fetch(`/api/work-items/${itemId}`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ title, work_type: workType, status, kanban_status: kanbanStatus })
                });

                if (resp.ok) {
                    showToast(`Updated item ${itemId}`);
                } else {
                    alert('Failed to save update');
                }
            }
        </script>
    </body>
    </html>
    """

    @app.route("/")
    def index():
        items = storage.get_work_items()
        high_conf = len([i for i in items if i.confidence >= 0.90])
        med_conf = len([i for i in items if 0.70 <= i.confidence < 0.90])
        low_conf = len([i for i in items if i.confidence < 0.70])

        backlog_count = len([i for i in items if i.kanban_status == KanbanStatus.BACKLOG])
        ready_count = len([i for i in items if i.kanban_status == KanbanStatus.READY_FOR_DEV])
        progress_count = len([i for i in items if i.kanban_status == KanbanStatus.IN_PROGRESS])
        done_count = len([i for i in items if i.kanban_status == KanbanStatus.DONE])

        return render_template_string(
            HTML_TEMPLATE,
            items=items,
            high_conf=high_conf,
            med_conf=med_conf,
            low_conf=low_conf,
            backlog_count=backlog_count,
            ready_count=ready_count,
            progress_count=progress_count,
            done_count=done_count,
            work_types=list(WorkType),
            statuses=list(WorkItemStatus),
            kanban_statuses=list(KanbanStatus)
        )

    @app.route("/api/work-items/<item_id>", methods=["POST"])
    def update_item(item_id):
        data = request.json
        items = {i.id: i for i in storage.get_work_items()}
        if item_id not in items:
            return jsonify({"error": "Item not found"}), 404

        item = items[item_id]
        if "title" in data:
            item.title = data["title"]
        if "work_type" in data:
            item.work_type = WorkType(data["work_type"])
        if "status" in data:
            item.status = WorkItemStatus(data["status"])
        if "kanban_status" in data:
            item.kanban_status = KanbanStatus(data["kanban_status"])

        storage.update_work_item(item)
        return jsonify({"success": True})

    return app

