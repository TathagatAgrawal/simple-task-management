// Friendly names for the response and request shapes generated from the API's OpenAPI schema.
// If the backend changes a field, `npm run types` regenerates schema.d.ts and the compiler shows
// every place in the client that needs to follow.
import type { components } from "./schema";

type Schemas = components["schemas"];

export type Me = Schemas["Me"];
export type Meta = Schemas["Meta"];
export type Person = Schemas["Person"];
export type Assignee = Schemas["Assignee"];
export type Card = Schemas["Card"];
export type Board = Schemas["Board"];
export type Summary = Schemas["Summary"];
export type SummaryItem = Schemas["SummaryItem"];
export type OtherOverdue = Schemas["OtherOverdue"];
export type Task = Schemas["Task"];
export type TaskPatched = Schemas["TaskPatched"];
export type Update = Schemas["Update"];
export type Notification = Schemas["Notification"];
export type Unread = Schemas["Unread"];
export type Option = Schemas["Option"];
export type Session = Schemas["Session"];
export type PersonCreated = Schemas["PersonCreated"];
export type TemporaryPassword = Schemas["TemporaryPassword"];
export type UpdateInfo = Schemas["UpdateInfo"];
export type PushInfo = Schemas["PushInfo"];
export type NotificationKind = Schemas["NotificationKind"];

export type TaskIn = Schemas["TaskIn"];
export type TaskPatch = Schemas["TaskPatch"];

export type Status = Card["status"];
export type Mode = "alert" | "inbox" | "off";
export type Theme = Me["theme"];
export type Settings = Record<string, Mode>;
