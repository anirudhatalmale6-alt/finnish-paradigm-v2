import csv
import json
import re
import sqlite3
from pathlib import Path

SEED_DIR = Path(__file__).resolve().parent.parent / "seed_data"


def _extract_sort_order(module_id: str) -> int:
    match = re.search(r"-M(\d+)$", module_id)
    return int(match.group(1)) if match else 0


def seed_upload_pack(db_path: str) -> None:
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    cur.execute("SELECT COUNT(*) FROM lms_courses")
    if cur.fetchone()[0] > 0:
        conn.close()
        return

    courses_file = SEED_DIR / "practical_courses_import.csv"
    with open(courses_file, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            cur.execute(
                """INSERT OR IGNORE INTO lms_courses
                   (course_id, slug, title, category, level, duration,
                    cpd_hours, audience, aim, module_count, published)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)""",
                (
                    row["course_id"],
                    row["slug"],
                    row["title"],
                    row["category"],
                    row["level"],
                    row["duration"],
                    row["cpd_hours"],
                    row["audience"],
                    row["aim"],
                    row["module_count"],
                ),
            )
            product_id = f"course-{row['course_id'].lower()}"
            cur.execute(
                """INSERT OR IGNORE INTO course_products
                   (course_id, product_id, payment_type, active)
                   VALUES (?, ?, 'one_time', 1)""",
                (row["course_id"], product_id),
            )

    modules_file = SEED_DIR / "practical_modules_import.csv"
    with open(modules_file, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            sort_order = _extract_sort_order(row["module_id"])
            video_script = row.get("video_script", "")
            cur.execute(
                """INSERT OR IGNORE INTO lms_modules
                   (module_id, course_id, title, scenario_setting,
                    scenario_problem, practice_steps, reflective_checklist,
                    video_script, sort_order, published)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1)""",
                (
                    row["module_id"],
                    row["course_id"],
                    row["title"],
                    row["scenario_setting"],
                    row["scenario_problem"],
                    row["practice_steps"],
                    row["checklist"],
                    video_script,
                    sort_order,
                ),
            )
            transcript = video_script[:500] if video_script else ""
            cur.execute(
                """INSERT OR IGNORE INTO module_videos
                   (module_id, video_status, transcript)
                   VALUES (?, 'script_ready', ?)""",
                (row["module_id"], transcript),
            )

    assessment_file = SEED_DIR / "practical_assessment_item_bank.csv"
    with open(assessment_file, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            cur.execute(
                """INSERT OR IGNORE INTO lms_assessment_items
                   (question_id, course_id, module_id, question,
                    question_type, answer_focus, published)
                   VALUES (?, ?, ?, ?, ?, ?, 1)""",
                (
                    row["question_id"],
                    row["course_id"],
                    row["module_id"],
                    row["question"],
                    row["type"],
                    row["answer_focus"],
                ),
            )

    content_file = SEED_DIR / "finnish_paradigm_lms_import.jsonl"
    if content_file.exists():
        with open(content_file, encoding="utf-8-sig") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                rec = json.loads(line)
                module_id = rec["id"]
                track = rec.get("course_track", "")
                title = rec.get("title", "")
                aim = rec.get("aim", "")
                overview = rec.get("overview", "")
                audience = "; ".join(rec.get("audience", []))
                objectives = json.dumps(rec.get("learning_objectives", []))
                outcomes = json.dumps(rec.get("outcomes", []))
                session_flow = json.dumps(rec.get("session_flow", []))
                activities = json.dumps(rec.get("activities", []))
                resources = json.dumps(rec.get("resources", []))
                assessment = rec.get("assessment", {})
                quiz_items = json.dumps(assessment.get("quiz_items", []) if isinstance(assessment, dict) else [])
                performance_task = assessment.get("performance_task", "") if isinstance(assessment, dict) else ""
                completion_criteria = assessment.get("completion_criteria", "") if isinstance(assessment, dict) else ""
                trainer_script = rec.get("trainer_script", "")
                scenario = json.dumps(rec.get("scenario", {}))
                demonstration = json.dumps(rec.get("demonstration_dialogue", []))
                leadership = json.dumps(rec.get("admin_implementation", []))
                metadata = json.dumps(rec.get("lms_fields", {}))

                cur.execute(
                    """INSERT OR IGNORE INTO website_modules
                       (module_id, track, title, aim, overview, audience,
                        objectives, outcomes, session_flow, activities,
                        resources, quiz_items, performance_task,
                        completion_criteria, trainer_script, scenario,
                        demonstration_dialogue, leadership_implementation,
                        lms_metadata, published)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,1)""",
                    (module_id, track, title, aim, overview, audience,
                     objectives, outcomes, session_flow, activities,
                     resources, quiz_items, performance_task,
                     completion_criteria, trainer_script, scenario,
                     demonstration, leadership, metadata),
                )

    conn.commit()
    conn.close()
