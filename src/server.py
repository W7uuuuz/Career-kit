"""Career Kit MCP 服务器——入口与工具装配。"""

from . import resources  # noqa: F401  注册 MCP Resources
from .mcp_app import mcp
from .tools.analysis_tools import analyze_gaps, explore_goals, save_gap_analysis
from .tools.application_list_tools import build_application_list
from .tools.application_tools import delete_application, record_application
from .tools.boss_tools import boss_login
from .tools.case_tools import search_cases
from .tools.claim_tools import list_claims, record_claim
from .tools.company_selection_tools import select_target_companies
from .tools.data_tools import (
    fetch_company_jobs,
    fetch_jd_detail,
    get_scraper_guide,
    import_plan,
    list_data_sources,
    search_knowledge,
)
from .tools.evidence_tools import collect_company_evidence
from .tools.execution_plan_tools import plan_execution_alignment, save_execution_alignment
from .tools.industry_tools import get_industry_snapshot
from .tools.plan_fit_tools import check_plan_fit
from .tools.profile_tools import (
    delete_profile,
    list_profiles,
    list_trash,
    restore_profile,
    switch_profile,
)
from .tools.requirement_tools import analyze_company_requirements, save_requirement_profile
from .tools.research_tools import gather_research_data, read_research_details, research_market
from .tools.roadmap_tools import generate_roadmap, save_roadmap, save_roadmap_audit
from .tools.session_tools import (
    finalize_profile,
    import_jd,
    import_jd_file,
    intake,
    parse_resume,
    start_session,
)
from .tools.task_tools import (
    apply_insight,
    checkin_task,
    detail_current_phase,
    generate_tasks,
    get_next_tasks,
    get_progress,
    get_weekly_review,
    get_workflow_status,
    save_current_detail,
    trigger_insight,
)
from .tools.tool_helpers import _json, _parse_json_param


def main():
    mcp.run()


if __name__ == "__main__":
    main()
