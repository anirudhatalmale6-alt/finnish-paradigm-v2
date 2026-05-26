COURSES = [
  {
    "id":"fcfp",
    "level":1,
    "title":"Foundational Certificate in Finnish Pedagogy (FCFP)",
    "audience":"Teachers",
    "duration":"6 weeks",
    "price":"149-299 USD",
    "outcome":"Restore teacher purpose, optimise solo-classroom practice, and apply Tier-1 early intervention.",
    "modules":["Rekindling Educator Purpose","The 45-15 Restorative Instructional Flow","Finnish-Inspired Equity and Well-Being","Immediate Verification Framework","Differentiation Without Extra Workload","Teacher Impact Portfolio"],
    "resources":["45-15 Daily Log Sheet","Early Warning Signs Checklist","Classroom Autonomy Matrix","Student Support Tracker","Mistake-Friendly Classroom Poster"]
  },
  {
    "id":"asti",
    "level":2,
    "title":"Advanced Specialist in Targeted Intervention (ASTI)",
    "audience":"Lead Teachers, Retired Specialists, SEN/Support Staff",
    "duration":"8 weeks",
    "price":"299-499 USD",
    "outcome":"Deploy retired teacher networks and fine-tune Tier 2 and Tier 3 support without forced co-teaching.",
    "modules":["Three-Tier Intervention Architecture","Senior Asset Precision Pull-Out Method","Progress Logs and Benchmark Reviews","Targeted Reading and Numeracy Support","Escalation Protocols","Intervention Case Study"],
    "resources":["Three-Tier Intervention Action Protocol","Senior Asset Deployment Matrix","Progress Log Template","Parent Communication Pack","Individualized Educational Strategy Template"]
  },
  {
    "id":"seld",
    "level":3,
    "title":"Strategic Educational Leadership Diploma (SELD)",
    "audience":"School Leaders, Directors, Ministries, Districts",
    "duration":"10 weeks",
    "price":"699-2500 USD",
    "outcome":"Build a whole-school early intervention operating system with dashboards, policy templates, staffing models, and quality metrics.",
    "modules":["Commercial and Institutional Implementation","School Culture Audit","Retired Teacher Network Funding and Operations","Data Dashboards and Quality Metrics","Legal and Ministry Alignment","School Transformation Capstone"],
    "resources":["School Culture Audit","Leadership Dashboard Template","Ministry Petition Framework","Budget Calculator","Retired Teacher Recruitment Engine"]
  }
]

PRODUCTS = [
  {"id":"teacher-starter","name":"Teacher Starter Bundle","price":"19 USD","includes":["Mini-course","Purpose workbook","Classroom posters","Sphere of Control worksheet"]},
  {"id":"early-intervention","name":"Early Intervention Toolkit","price":"49 USD","includes":["Tier protocol","Risk map","Student trackers","Parent templates","Intervention review forms"]},
  {"id":"school-leadership","name":"School Leadership Implementation Pack","price":"149 USD","includes":["Policy templates","Culture audit","Meeting agendas","Dashboards","Retired teacher programme guide"]},
  {"id":"retired-mentor","name":"Retired Teacher Intervention Mentor Pack","price":"99 USD","includes":["Mentor training","Safeguarding checklist","Session plans","Progress logs","Feedback forms"]},
  {"id":"enterprise","name":"Whole-School / Ministry License","price":"Custom","includes":["All courses","Admin dashboard","Assessment engine","PDF library","Implementation support architecture"]}
]

TOOLS = [
  {"id":"45-15-log","title":"45-15 Instructional Flow Daily Log", "category":"Classroom", "summary":"Daily planner for 45 minutes of focused instruction plus 15 minutes of restorative observation and micro-intervention."},
  {"id":"ivf-cards","title":"Immediate Verification Framework Cards", "category":"Assessment", "summary":"Green/Yellow/Red checkpoints for real-time comprehension monitoring during independent work."},
  {"id":"tier-protocol","title":"Three-Tier Intervention Action Protocol", "category":"Intervention", "summary":"Defines Level 1 classroom support, Level 2 targeted support, and Level 3 intensive customized support."},
  {"id":"senior-matrix","title":"Senior Asset Deployment Matrix", "category":"Retired Teachers", "summary":"Onboarding, scheduling, handover, and progress logging system for retired teacher intervention specialists."},
  {"id":"petition-framework","title":"Direct Ministry Petition and Evidence Framework", "category":"Escalation", "summary":"Professional evidence-based template for collective teacher advocacy when school support systems are blocked."},
  {"id":"autonomy-matrix","title":"Classroom Autonomy Matrix", "category":"Teacher Autonomy", "summary":"Helps teachers separate what they control, influence, and escalate."},
  {"id":"parent-pack","title":"Parent Communication Pack", "category":"Family Engagement", "summary":"Supportive messages for early support notices, positive progress, and meeting requests."},
  {"id":"ai-prompt-vault","title":"AI Prompt Vault for Finnish Paradigm Lesson Planning", "category":"AI Resources", "summary":"Copy-paste prompts to generate lesson plans using 45-15, IVF, and intervention asset protocols."}
]

VIDEOS = [
  {"id":"v01","course":"fcfp","title":"Somewhere We Got Lost","presenter":"Elena","length":"4:30","script":"Every morning, you enter your classroom carrying a profound responsibility. Beneath paperwork, routine, and pressure, the spark that called you to teaching can begin to dim. The Finnish-inspired approach helps you return to the human centre of education: trust, balance, early support, and dignity. You may not control the whole system, but you can control the learning climate inside your classroom. Today we strip away the noise and rebuild purpose.","prompt":"Create a professional AI presenter video. Avatar: mature female educator, warm, authoritative, Scandinavian-inspired classroom backdrop, light wood accents, navy blazer, measured cadence."},
  {"id":"v02","course":"fcfp","title":"The 45-15 Restorative Instructional Flow","presenter":"Elena","length":"6:00","script":"The 45-15 flow divides a 60-minute lesson into 45 minutes of focused teaching and guided practice, followed by 15 minutes of restorative movement, reflection, and teacher observation. This does not reduce learning. It protects attention and creates a window for early identification.","prompt":"AI video with timeline diagram on whiteboard. Presenter explains 5-minute focus accelerator, 20-minute direct instruction, 20-minute guided practice, 15-minute restorative observation."},
  {"id":"v03","course":"asti","title":"The Three-Tier Intervention Model","presenter":"Marcus","length":"7:00","script":"Intervention must not wait for failure. Tier 1 is high-quality solo-classroom support. Tier 2 begins when evidence shows repeated difficulty. Tier 3 is intensive customized support. The teacher remains the captain of the classroom while the intervention layer stabilizes learning.","prompt":"Corporate training video. Male executive educator, grey suit, digital 3-tier pyramid, analytical tone, institutional polish."},
  {"id":"v04","course":"asti","title":"Deploying Senior Assets","presenter":"Elena","length":"6:30","script":"Retired educators are one of the greatest untapped resources in education. They can provide reading, numeracy, language, confidence, and homework recovery support without taking over the classroom or creating split authority.","prompt":"B2B principal-facing video, boardroom background, calm persuasive tone, senior asset deployment diagram."},
  {"id":"v05","course":"seld","title":"Leadership Dashboard and Quality Metrics","presenter":"Marcus","length":"8:00","script":"A school cannot improve what it cannot see. The leadership dashboard tracks students at risk, intervention cycles, benchmark progress, retired specialist sessions, parent contact, and unresolved escalation cases.","prompt":"High-end school leadership video, dashboard screen, calm strategic delivery, data-informed improvement tone."},
  {"id":"v06","course":"seld","title":"Professional Escalation and Ministry Alignment","presenter":"Marcus","length":"7:30","script":"Teachers should advocate professionally and lawfully. Escalation begins with evidence, written proposals, leadership requests, and documented student benefit. Ministry petitions must be respectful, policy-aligned, and focused on the child.","prompt":"Serious think-tank backdrop, firm professional tone, legal-safe teacher advocacy framing."}
]

ESCALATION_PROTOCOLS = [
  {"level":"Classroom","trigger":"First signs of difficulty","owner":"Teacher","action":"Use Level 1 support, record evidence, apply scaffolds, review in 1-2 weeks."},
  {"level":"Department","trigger":"Three repeated red/yellow IVF markers in one week","owner":"Teacher + Department Lead","action":"Open Tier 2 case, schedule targeted support, log intervention plan."},
  {"level":"School Support Team","trigger":"No benchmark improvement after 14-day Tier 2 cycle","owner":"Support Coordinator / Management","action":"Create Individualized Educational Strategy, contact parents, schedule review."},
  {"level":"External / Specialist","trigger":"Persistent serious concern or safeguarding issue","owner":"School Leader","action":"Follow local policy, refer to specialist, document decisions."},
  {"level":"Professional Advocacy","trigger":"Systemic refusal to provide support systems","owner":"Allied Faculty","action":"Submit evidence-based proposal to leadership first; if lawful and necessary, escalate through official ministry channels."}
]

AUTONOMY_MATRIX = [
  {"domain":"Lesson design","teacher_control":"High","school_support":"Medium","escalation":"None","examples":"Scaffolds, examples, pacing, guided practice, checklists."},
  {"domain":"Classroom climate","teacher_control":"High","school_support":"Medium","escalation":"None","examples":"Tone, routines, mistake-friendly culture, seating support."},
  {"domain":"Early intervention recording","teacher_control":"High","school_support":"High","escalation":"Department if patterns persist","examples":"Student risk map, IVF results, progress notes."},
  {"domain":"Tier 2 support scheduling","teacher_control":"Medium","school_support":"High","escalation":"Management if unavailable","examples":"Small-group sessions, retired teacher deployment, study blocks."},
  {"domain":"Tier 3 individualized support","teacher_control":"Low-Medium","school_support":"High","escalation":"Specialist/school leadership","examples":"IES plan, parent meeting, external referral."},
  {"domain":"Policy change","teacher_control":"Low","school_support":"High","escalation":"Official proposal/ministry route","examples":"Staffing models, timetable structures, institutional budget."}
]
