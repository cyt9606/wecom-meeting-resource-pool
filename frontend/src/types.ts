export interface Policy {
  buffer_minutes: number;
  min_lead_minutes: number;
  max_duration_minutes: number;
  max_advance_days: number;
  max_pending_per_user: number;
}

export interface CurrentUser {
  userid: string;
  is_admin: boolean;
  policy: Policy;
}

export interface JoinInfo {
  external_join_url?: string | null;
  numeric_meeting_code?: string | null;
  password?: string | null;
}

export interface Reservation {
  id: string;
  status: string;
  title: string;
  description: string;
  start_at: string;
  end_at: string;
  meetingid?: string | null;
  host_userid?: string | null;
  resource_display_name?: string | null;
  join_info: JoinInfo;
  allow_external_user: boolean;
  enable_waiting_room: boolean;
  last_error?: string | null;
  created_at: string;
  updated_at: string;
}

export interface Resource {
  id: string;
  wecom_userid: string;
  display_name: string;
  priority: number;
  enabled: boolean;
  health_status: string;
  allocation_count: number;
  allocated_seconds: number;
}

export interface Admin {
  userid: string;
  created_by?: string | null;
  created_at: string;
}
