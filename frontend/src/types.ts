export interface ToolDescriptor {
  name: string;
  title?: string | null;
  description?: string | null;
  ui_resource_uri?: string | null;
}

export interface ToolCallResult {
  is_error: boolean;
}

export interface ToolCallRecord {
  call_id: string;
  tool_name: string;
  status: string;
  result?: ToolCallResult | null;
}

export interface AppResource {
  uri: string;
  mime_type: string;
  text?: string | null;
}

export interface BridgeSessionSnapshot {
  session_id: string;
  status: string;
  discovered_tools: ToolDescriptor[];
  active_tool_calls: ToolCallRecord[];
  loaded_resources: AppResource[];
  last_error?: string | null;
  event_count: number;
}

export interface SessionEvent {
  event_id: string;
  session_id: string;
  kind: string;
  created_at: string;
  tool?: ToolDescriptor;
  call?: ToolCallRecord;
  resource?: AppResource;
  message?: string;
}

export interface EventBatch {
  after: number;
  events: SessionEvent[];
}