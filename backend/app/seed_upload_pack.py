import json
import sqlite3
from pathlib import Path

SEED_DIR = Path(__file__).resolve().parent.parent / "seed_data"


def seed_upload_pack(db_path: str) -> None:
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    cur.execute("SELECT COUNT(*) FROM lms_courses")
    if cur.fetchone()[0] > 0:
        conn.close()
        return

    courses_file = SEED_DIR / "courses.json"
    with open(courses_file, encoding="utf-8") as f:
        courses = json.load(f)
    for c in courses:
        cur.execute(
            """INSERT OR IGNORE INTO lms_courses
               (course_id, slug, title, purpose, programme_id, level,
                audience, delivery_mode, cpd_hours, certificate_wording,
                module_count, status, published)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)""",
            (
                c["id"], c["slug"], c["title"], c.get("purpose", ""),
                c.get("programme_id", ""), c.get("level", ""),
                c.get("audience", ""), c.get("delivery_mode", ""),
                c.get("cpd_hours", 3), c.get("certificate_wording", ""),
                len(c.get("module_ids", [])), c.get("status", "release_candidate"),
            ),
        )
        product_id = f"course-{c['id'].lower()}"
        cur.execute(
            """INSERT OR IGNORE INTO course_products
               (course_id, product_id, payment_type, active)
               VALUES (?, ?, 'one_time', 1)""",
            (c["id"], product_id),
        )

    modules_file = SEED_DIR / "modules.json"
    with open(modules_file, encoding="utf-8") as f:
        modules = json.load(f)
    for i, m in enumerate(modules):
        cur.execute(
            """INSERT OR IGNORE INTO lms_modules
               (module_id, course_id, slug, title, aim, objectives, outcomes,
                key_concepts, scenarios, estimated_video_minutes,
                estimated_module_minutes, lesson_type, sort_order,
                status, published)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)""",
            (
                m["id"], m["course_id"], m.get("slug", ""),
                m["title"], m.get("aim", ""),
                json.dumps(m.get("objectives", [])),
                json.dumps(m.get("outcomes", [])),
                json.dumps(m.get("key_concepts", [])),
                json.dumps(m.get("scenarios", [])),
                m.get("estimated_video_minutes", 6),
                m.get("estimated_module_minutes", 90),
                m.get("lesson_type", "scenario_based_cpd"),
                i + 1, m.get("status", "release_candidate"),
            ),
        )

    quizzes_file = SEED_DIR / "quizzes.json"
    with open(quizzes_file, encoding="utf-8") as f:
        quizzes = json.load(f)
    for q in quizzes:
        cur.execute(
            """INSERT OR IGNORE INTO lms_quizzes
               (quiz_id, module_id, question, choices,
                correct_choice_index, feedback)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                q["id"], q["module_id"], q["question"],
                json.dumps(q.get("choices", [])),
                q.get("correct_choice_index", 0),
                q.get("feedback", ""),
            ),
        )

    rubrics_file = SEED_DIR / "rubrics.json"
    with open(rubrics_file, encoding="utf-8") as f:
        rubrics = json.load(f)
    for r in rubrics:
        cur.execute(
            """INSERT OR IGNORE INTO lms_rubrics
               (module_id, criterion, excellent, secure, developing)
               VALUES (?, ?, ?, ?, ?)""",
            (
                r["module_id"], r["criterion"],
                r.get("excellent", ""), r.get("secure", ""),
                r.get("developing", ""),
            ),
        )

    tasks_file = SEED_DIR / "implementation_tasks.json"
    with open(tasks_file, encoding="utf-8") as f:
        tasks = json.load(f)
    for t in tasks:
        cur.execute(
            """INSERT OR IGNORE INTO lms_implementation_tasks
               (task_id, module_id, title, instructions,
                evidence_required, pass_rule)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                t["id"], t["module_id"], t["title"],
                t.get("instructions", ""),
                json.dumps(t.get("evidence_required", [])),
                t.get("pass_rule", ""),
            ),
        )

    resources_file = SEED_DIR / "resources.json"
    with open(resources_file, encoding="utf-8") as f:
        resources = json.load(f)
    for res in resources:
        cur.execute(
            """INSERT OR IGNORE INTO lms_resources
               (resource_id, title, resource_type, resource_path, module_ids)
               VALUES (?, ?, ?, ?, ?)""",
            (
                res["id"], res["title"], res.get("type", ""),
                res.get("path", ""),
                json.dumps(res.get("module_ids", [])),
            ),
        )

    video_scripts_file = SEED_DIR / "video_scripts.json"
    with open(video_scripts_file, encoding="utf-8") as f:
        video_scripts = json.load(f)
    for vs in video_scripts:
        cur.execute(
            """INSERT OR IGNORE INTO module_videos
               (module_id, video_status, transcript, video_duration_seconds)
               VALUES (?, 'script_ready', ?, ?)""",
            (
                vs["module_id"],
                json.dumps(vs.get("scenes", [])),
                (vs.get("duration_minutes", 6) * 60),
            ),
        )
        cur.execute(
            """INSERT OR IGNORE INTO lms_video_scripts
               (script_id, module_id, title, duration_minutes,
                format, avatar_direction, scenes)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                vs["id"], vs["module_id"], vs["title"],
                vs.get("duration_minutes", 6),
                vs.get("format", ""),
                vs.get("avatar_direction", ""),
                json.dumps(vs.get("scenes", [])),
            ),
        )

    glossary_file = SEED_DIR / "glossary.json"
    with open(glossary_file, encoding="utf-8") as f:
        glossary = json.load(f)
    for g in glossary:
        cur.execute(
            """INSERT OR IGNORE INTO lms_glossary
               (concept, meaning, practice)
               VALUES (?, ?, ?)""",
            (g["concept"], g.get("meaning", ""), g.get("practice", "")),
        )

    programme_file = SEED_DIR / "programme.json"
    with open(programme_file, encoding="utf-8") as f:
        programme = json.load(f)
    cur.execute(
        """INSERT OR IGNORE INTO lms_programme
           (programme_id, brand, short_name, title, version,
            release_date, ethical_positioning, core_video_pattern,
            global_outcomes, source_basis)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            programme["id"], programme.get("brand", ""),
            programme.get("short_name", ""),
            programme.get("title", ""), programme.get("version", ""),
            programme.get("release_date", ""),
            programme.get("ethical_positioning", ""),
            json.dumps(programme.get("core_video_pattern", [])),
            json.dumps(programme.get("global_outcomes", [])),
            json.dumps(programme.get("source_basis", [])),
        ),
    )

    cert_rules_file = SEED_DIR / "certificate_rules.json"
    with open(cert_rules_file, encoding="utf-8") as f:
        cert_rules = json.load(f)
    cur.execute(
        """INSERT OR IGNORE INTO lms_certificate_rules
           (programme_id, rules_json)
           VALUES (?, ?)""",
        (cert_rules.get("programme_id", ""), json.dumps(cert_rules)),
    )

    tvet_file = SEED_DIR / "tvet_modules.json"
    if tvet_file.exists():
        with open(tvet_file, encoding="utf-8") as f:
            tvet = json.load(f)
        for t in tvet:
            cur.execute(
                """INSERT OR IGNORE INTO tvet_modules
                   (tvet_id, slug, title, purpose, topic, task, scenario, demo)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    t["id"], t.get("slug", ""), t["title"],
                    t.get("purpose", ""), t.get("topic", ""),
                    t.get("task", ""), t.get("scenario", ""),
                    t.get("demo", ""),
                ),
            )

    consultancy_file = SEED_DIR / "consultancy_services.json"
    if consultancy_file.exists():
        with open(consultancy_file, encoding="utf-8") as f:
            services = json.load(f)
        for s in services:
            cur.execute(
                """INSERT OR IGNORE INTO consultancy_services
                   (service_id, slug, title, description)
                   VALUES (?, ?, ?, ?)""",
                (
                    s["id"], s.get("slug", ""), s["title"],
                    s.get("description", ""),
                ),
            )

    conn.commit()
    conn.close()
