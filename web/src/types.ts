export interface TaskResource {
  label?: string
  url?: string
  search?: string
}

export interface Task {
  id: string
  name: string
  desc: string
  status: string
  priority: string
  milestone_id: string | null
  checkin_mode: string
  checkin_goal: number | null
  checkin_progress: number
  how_to: string[]
  resources: TaskResource[]
  done_criteria: string
}

export interface MilestoneTask {
  name: string
  desc: string
  priority: string
  done_criteria: string
}

export interface Phase {
  id: string
  name: string
  type: string
  type_label: string
  goal: string
  company: string
  rationale: string
  is_current: boolean
  done: number
  total: number
  milestone_names: Record<string, string>
  milestone_tasks: MilestoneTask[]
  tasks: Task[]
}

export interface CompanyPoolInfo {
  id: string
  counts: Record<string, number>
  scrapable: string[]
  not_scrapable: string[]
}

export interface EvidenceInfo {
  id: string
  counts: Record<string, number>
  confidence: Record<string, string>
  report_html: string
  report_md: string
  index: string
}

export interface RequirementInfo {
  id: string
  high_frequency_count: number
  hard_requirement_count: number
  confidence_jd: string
  confidence_interview: string
}

export interface ExecutionPlanInfo {
  id: string
  applied: boolean
  strategy_summary: string
  phase_count: number
  diff_summary: string
}

export interface Alignment {
  stage: string
  company_pool: CompanyPoolInfo | null
  evidence: EvidenceInfo | null
  requirement: RequirementInfo | null
  execution_plan: ExecutionPlanInfo | null
  next_tool: string
}

export interface ResearchInfo {
  generated_at?: string
  counts?: Record<string, number>
  report_html?: string
  report_md?: string
  report_json?: string
  failed_sources?: string[]
}

export interface ReportInfo {
  direction: string
  generated_at: string
  counts: Record<string, number>
  failed_sources: string[]
  html: string
  md: string
  json: string
}

export interface ApplicationInfo {
  id: string
  company: string
  role: string
  status: string
  channel: string
  applied_at: string
}

export interface AppState {
  profile: string
  start_level: string
  strategy: string
  phases: Phase[]
  total_done: number
  total_tasks: number
  all_complete: boolean
  warnings: string[]
  assets_index: string
  research: ResearchInfo
  reports: ReportInfo[]
  applications: ApplicationInfo[]
  alignment: Alignment
  sync_warning?: string
}
