"""Career Kit MCP 服务器——入口与工具装配。"""

from . import resources  # noqa: F401  注册 MCP Resources
from .mcp_app import mcp
from .tools.analysis_tools import analyze_gaps, explore_goals, save_gap_analysis
from .tools.application_tools import delete_application, record_application
from .tools.case_tools import search_cases
from .tools.dashboard import (
    render_progress_html as _render_progress_html,
    render_roadmap_map as _render_roadmap_map,
    write_html as _write_html,
)
from .tools.data_tools import (
    fetch_company_jobs,
    fetch_jd_detail,
    get_scraper_guide,
    import_plan,
    list_data_sources,
    search_knowledge,
)
from .tools.profile_tools import (
    delete_profile,
    list_profiles,
    list_trash,
    restore_profile,
    switch_profile,
)
from .tools.research_tools import gather_research_data, research_market
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
    export_dashboard,
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
