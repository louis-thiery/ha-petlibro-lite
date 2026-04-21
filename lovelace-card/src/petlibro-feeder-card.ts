/**
 * petlibro-feeder-card — standalone Lovelace custom card for the
 * ha-petlibro-lite HACS integration.
 *
 * Compact at-a-glance card: camera thumb, cat icon, name, warning badge,
 * last-fed summary, and 1/2/3 portion feed buttons. Two buttons open
 * dialogs for recent feed log and schedule editor.
 *
 * The camera thumbnail renders a "Connecting…" overlay while the
 * integration's stream driver is still handshaking with the feeder —
 * driven by the camera entity's `stream_state` attribute so cards stay
 * in sync with reality without polling.
 *
 * Stays quiet when everything's fine: food-level chip only surfaces on
 * low/empty, status badge only when something's unusual.
 *
 * Config (see README for the full list):
 *
 *   type: custom:petlibro-feeder-card
 *   feed_number: number.petlibro_lite_xxx_feed_portions         # required
 *   name: Cat Feeder                                            # optional
 *   portions: [1, 2]                                            # optional; preset buttons, default [1, 2] (a "…" always follows for custom 1-50)
 *   state_sensor: sensor.petlibro_lite_xxx_state
 *   food_level_sensor: sensor.petlibro_lite_xxx_food_level
 *   last_manual_sensor: sensor.petlibro_lite_xxx_last_manual_feed
 *   last_scheduled_sensor: sensor.petlibro_lite_xxx_last_scheduled_feed
 *   warning_sensor: sensor.petlibro_lite_xxx_warning
 *   feed_log_sensor: sensor.petlibro_lite_xxx_feed_log          # enables log section
 *   schedules_sensor: sensor.petlibro_lite_xxx_schedules        # enables schedule section
 *   device_id: <tuya_device_id>                                 # required for schedule edits
 *   camera_entity: camera.petlibro_lite_xxx_camera
 */

import { LitElement, html, css, nothing, type TemplateResult } from "lit"
import { customElement, property, state } from "lit/decorators.js"

interface HassState {
  entity_id: string
  state: string
  attributes: Record<string, unknown>
  last_changed: string
  last_updated: string
}

interface Hass {
  states: Record<string, HassState>
  callService: (
    domain: string,
    service: string,
    data?: Record<string, unknown>,
    target?: { entity_id?: string | string[] },
  ) => Promise<unknown>
  hassUrl?: (path?: string) => string
  auth?: { data: { access_token: string } }
}

interface CardConfig {
  name?: string
  feed_number: string
  portions?: number[]
  state_sensor?: string
  food_level_sensor?: string
  last_manual_sensor?: string
  last_scheduled_sensor?: string
  warning_sensor?: string
  feed_log_sensor?: string
  schedules_sensor?: string
  next_feed_sensor?: string
  portions_today_sensor?: string
  device_id?: string
  camera_entity?: string
}

// Entries emitted by `sensor.*_feed_log` via the `entries` attribute. The
// Python integration distinguishes manual vs scheduled feeds (matching the
// PetLibro cloud log's granularity) and emits warnings with a numeric code.
interface LogEntry {
  time: number // Unix seconds
  kind: "manual" | "scheduled" | "warning"
  portions?: number
  code?: number
}

// DP 236 warning code → human label (matches the integration's
// WARNING_LABELS in const.py). Kept small on purpose; unknown codes
// fall through as "warning <n>".
const WARNING_CODE_LABEL: Record<number, string> = {
  2: "Outlet blocked",
}

interface ScheduleSlot {
  hour: number
  minute: number
  portions: number
  enabled: boolean
  days: string[]
}

// Values the integration's warning sensor emits that count as "nothing wrong".
const WARNING_OK_STATES = new Set(["ok", "0", "none", "unknown", "unavailable"])
const FOOD_ALERT_STATES = new Set(["low", "empty"])

const DAY_ORDER = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"] as const
const DAY_LABEL: Record<string, string> = {
  mon: "M", tue: "T", wed: "W", thu: "T", fri: "F", sat: "S", sun: "S",
}

function formatDays(days: readonly string[]): string {
  const set = new Set(days.map((d) => d.toLowerCase()))
  if (DAY_ORDER.every((d) => set.has(d))) return "Every day"
  const weekdays: readonly string[] = DAY_ORDER.slice(0, 5)
  const weekend: readonly string[] = ["sat", "sun"]
  if (
    weekdays.every((d) => set.has(d)) &&
    weekend.every((d) => !set.has(d))
  ) return "Weekdays"
  if (
    weekend.every((d) => set.has(d)) &&
    weekdays.every((d) => !set.has(d))
  ) return "Weekends"
  return DAY_ORDER
    .filter((d) => set.has(d))
    .map((d) => d[0].toUpperCase() + d.slice(1))
    .join(", ")
}

function formatHM(h: number, m: number): string {
  return `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}`
}

/** 12-hour human format, e.g. "6:00 PM". Minutes hide when :00 for brevity. */
function formatHMDisplay(h: number, m: number): string {
  const suffix = h >= 12 ? "PM" : "AM"
  const h12 = h % 12 || 12
  return m === 0
    ? `${h12} ${suffix}`
    : `${h12}:${String(m).padStart(2, "0")} ${suffix}`
}

/** Compact human format for `sensor.*_next_feed` (TIMESTAMP state).
 *  Returns e.g. "Today, 6 PM", "Tomorrow, 9 AM", or "Thu, 6 PM".
 *  Empty string if the sensor state isn't a parseable timestamp. */
function formatNextFeedWhen(iso: string): string {
  const t = Date.parse(iso)
  if (Number.isNaN(t)) return ""
  const target = new Date(t)
  const now = new Date()
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate())
  const diffDays = Math.floor(
    (new Date(target.getFullYear(), target.getMonth(), target.getDate()).getTime() -
      today.getTime()) / 86400_000,
  )
  const time = formatHMDisplay(target.getHours(), target.getMinutes())
  if (diffDays === 0) return `Today, ${time}`
  if (diffDays === 1) return `Tomorrow, ${time}`
  const weekday = target.toLocaleDateString(undefined, { weekday: "short" })
  return `${weekday}, ${time}`
}

const MAX_CUSTOM_PORTIONS = 50

// Which driver phases count as "still warming up" — we show the overlay
// until the first real frame lands.
const CONNECTING_PHASES = new Set(["signaling", "ice", "auth", "waiting_frame"])
const PHASE_LABEL: Record<string, string> = {
  signaling: "Connecting…",
  ice: "Establishing link…",
  auth: "Authorizing…",
  waiting_frame: "Waiting for first frame…",
  streaming: "Live",
  error: "Camera error",
  idle: "",
}

@customElement("petlibro-feeder-card")
export class PetLibroFeederCard extends LitElement {
  @property({ attribute: false })
  hass?: Hass

  @state()
  private _config?: CardConfig

  @state()
  private _pendingPortions: number | null = null

  // When true, the feed-row swaps to a number-input + Feed/Cancel instead
  // of the preset portion buttons. Lets users dispense any amount 1..50
  // (matching the PetLibro app's range). Reset on feed/cancel.
  @state()
  private _customPortionsMode = false

  @state()
  private _customPortionsValue = 4

  @state()
  private _dialogMode: "log" | "schedules" | null = null

  @state()
  private _editing: { mode: "add" } | { mode: "edit"; index: number } | null = null

  @state()
  private _editDraft: ScheduleSlot | null = null

  @state()
  private _savingSchedule = false

  // Optimistic schedule override: set on delete/toggle/save so the UI
  // reacts instantly. Cleared once the HA sensor catches up (slots match
  // what we asked for) or when the dialog closes.
  @state()
  private _optimisticSlots: ScheduleSlot[] | null = null

  // Last-seen slots list. If the sensor attribute briefly goes away
  // (HA startup, WebSocket reconnect) we render this instead of flashing
  // "no schedules available". Not a @state — we mutate it in place during
  // _schedules() which is called from render(), and we only care about it
  // being current by the next render tick.
  private _lastSeenSlots: ScheduleSlot[] | null = null

  // Interval id for the dialog-open repoll loop. Kept on the instance so
  // disconnectedCallback + _closeDialog can clean it up deterministically.
  private _dialogRefreshTimer: number | null = null

  setConfig(config: CardConfig): void {
    if (!config?.feed_number) {
      throw new Error("petlibro-feeder-card: 'feed_number' is required")
    }
    this._config = config
  }

  getCardSize(): number {
    return this._config?.camera_entity ? 5 : 2
  }

  static getStubConfig(): CardConfig {
    return { name: "PetLibro", feed_number: "", portions: [1, 2] }
  }

  private _s(entityId?: string): HassState | undefined {
    if (!entityId || !this.hass) return undefined
    return this.hass.states[entityId]
  }

  private _relativeTime(iso: string | number | undefined): string {
    if (iso == null) return "—"
    const t = typeof iso === "number" ? iso * 1000 : Date.parse(iso)
    if (Number.isNaN(t)) return "—"
    const diff = (Date.now() - t) / 1000
    if (diff < 60) return "just now"
    if (diff < 3600) return `${Math.floor(diff / 60)}m ago`
    if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`
    return `${Math.floor(diff / 86400)}d ago`
  }

  private async _feed(portions: number): Promise<void> {
    if (!this.hass || !this._config || this._pendingPortions !== null) return
    const clamped = Math.max(1, Math.min(MAX_CUSTOM_PORTIONS, Math.floor(portions)))
    this._pendingPortions = clamped
    // Close the custom-portions overlay if the feed was initiated from it.
    this._customPortionsMode = false
    try {
      await this.hass.callService(
        "number",
        "set_value",
        { value: clamped },
        { entity_id: this._config.feed_number },
      )
    } finally {
      // Keep the pending indicator for a moment so buttons don't flash
      // back to idle before the feed physically runs (~10s).
      setTimeout(() => {
        this._pendingPortions = null
      }, 2500)
    }
  }

  private _openCustomPortions(): void {
    this._customPortionsMode = true
  }

  private _cancelCustomPortions(): void {
    this._customPortionsMode = false
  }

  private _onCustomPortionsInput(e: Event): void {
    const target = e.target as HTMLInputElement
    const n = Number(target.value)
    if (!Number.isFinite(n)) return
    this._customPortionsValue = Math.max(1, Math.min(MAX_CUSTOM_PORTIONS, Math.floor(n)))
  }

  private _submitCustomPortions(): void {
    this._feed(this._customPortionsValue)
  }

  private _openMore(entityId?: string): void {
    if (!entityId) return
    const event = new Event("hass-more-info", {
      bubbles: true,
      composed: true,
    })
    ;(event as Event & { detail?: { entityId: string } }).detail = { entityId }
    this.dispatchEvent(event)
  }

  /** Compact row under the status card: next feed + portions today. Hidden
   *  entirely when neither sensor is wired so legacy configs still render
   *  cleanly. */
  private _renderGlance() {
    const nextSensor = this._s(this._config?.next_feed_sensor)
    const todaySensor = this._s(this._config?.portions_today_sensor)
    if (!nextSensor && !todaySensor) return nothing

    const nextWhen =
      nextSensor && nextSensor.state !== "unknown" && nextSensor.state !== "unavailable"
        ? formatNextFeedWhen(nextSensor.state)
        : ""
    const nextPortions = Number(
      (nextSensor?.attributes as Record<string, unknown> | undefined)?.portions ?? 0,
    )
    const todayRaw = todaySensor?.state
    const todayN =
      todayRaw && todayRaw !== "unknown" && todayRaw !== "unavailable"
        ? Number(todayRaw)
        : NaN

    return html`
      <div class="glance">
        ${nextSensor
          ? html`
              <div
                class="glance-item"
                @click=${() => this._openMore(this._config!.next_feed_sensor)}
                role="button"
                tabindex="0"
              >
                <ha-icon icon="mdi:calendar-clock"></ha-icon>
                <div class="glance-text">
                  <div class="glance-label">Next feed</div>
                  <div class="glance-value">
                    ${nextWhen || "—"}${nextPortions > 0
                      ? html` · <span class="portions"
                            >${nextPortions}p</span
                          >`
                      : nothing}
                  </div>
                </div>
              </div>
            `
          : nothing}
        ${todaySensor
          ? html`
              <div
                class="glance-item"
                @click=${() => this._openMore(this._config!.portions_today_sensor)}
                role="button"
                tabindex="0"
              >
                <ha-icon icon="mdi:counter"></ha-icon>
                <div class="glance-text">
                  <div class="glance-label">Today</div>
                  <div class="glance-value">
                    ${Number.isFinite(todayN)
                      ? html`${todayN}
                          <span class="glance-unit"
                            >portion${todayN === 1 ? "" : "s"}</span
                          >`
                      : "—"}
                  </div>
                </div>
              </div>
            `
          : nothing}
      </div>
    `
  }

  private _openDialog(mode: "log" | "schedules"): void {
    this._dialogMode = mode
    this._refreshForDialog(mode)
    // Keep polling while the dialog is open so edits made on the PetLibro
    // app side reflect in HA within a few seconds instead of waiting for
    // the 10s background tick. Cleared on close / disconnect.
    if (this._dialogRefreshTimer !== null) {
      window.clearInterval(this._dialogRefreshTimer)
    }
    this._dialogRefreshTimer = window.setInterval(() => {
      this._refreshForDialog(mode)
    }, 3000)
  }

  private _refreshForDialog(mode: "log" | "schedules"): void {
    if (!this.hass) return
    const deviceId = this._config?.device_id
    const payload = deviceId ? { device_id: deviceId } : {}
    // Schedules: fresh DP 231 from the feeder over LAN. Log: cloud poll.
    // The log dialog benefits from a state refresh too (updates the
    // "last fed" relative time + warning sensor), so call both in that
    // case.
    const services: string[] = ["refresh_state"]
    // `mode` is kept in the signature for symmetry with future modes, but
    // both Activity and Schedules just need a fresh LAN poll — the rolling
    // feed log reacts to the same bus events the coordinator fires.
    void mode
    for (const svc of services) {
      this.hass
        .callService("petlibro_lite", svc, payload)
        .catch(() => {
          /* non-fatal */
        })
    }
  }

  private _closeDialog(): void {
    this._dialogMode = null
    this._editing = null
    this._editDraft = null
    this._optimisticSlots = null
    if (this._dialogRefreshTimer !== null) {
      window.clearInterval(this._dialogRefreshTimer)
      this._dialogRefreshTimer = null
    }
  }

  disconnectedCallback(): void {
    super.disconnectedCallback()
    if (this._dialogRefreshTimer !== null) {
      window.clearInterval(this._dialogRefreshTimer)
      this._dialogRefreshTimer = null
    }
  }

  private _latestFed(
    manual: HassState | undefined,
    scheduled: HassState | undefined,
  ): { iso: string; portions?: number; kind: "manual" | "scheduled" } | undefined {
    const pickTime = (s: HassState | undefined) =>
      s && s.state !== "unknown" && s.state !== "unavailable" ? s.state : undefined
    const manualIso = pickTime(manual)
    const scheduledIso = pickTime(scheduled)
    if (!manualIso && !scheduledIso) return undefined
    const manualTs = manualIso ? Date.parse(manualIso) : 0
    const schedTs = scheduledIso ? Date.parse(scheduledIso) : 0
    const useManual = manualTs >= schedTs && manualIso
    const iso = useManual ? manualIso! : scheduledIso!
    const src = useManual ? manual : scheduled
    const portionsAttr = src?.attributes?.portions
    const portions =
      typeof portionsAttr === "number"
        ? portionsAttr
        : typeof portionsAttr === "string"
          ? Number(portionsAttr) || undefined
          : undefined
    return { iso, portions, kind: useManual ? "manual" : "scheduled" }
  }

  private _logEntries(): LogEntry[] {
    const sensor = this._s(this._config?.feed_log_sensor)
    const raw = sensor?.attributes?.entries
    if (!Array.isArray(raw)) return []
    return raw as LogEntry[]
  }

  private _schedules(): ScheduleSlot[] {
    // Optimistic override: when a local mutation is in flight, show what
    // the user *just did* — not the stale sensor value. Cleared below when
    // the sensor catches up.
    if (this._optimisticSlots !== null) return this._optimisticSlots
    const sensor = this._s(this._config?.schedules_sensor)
    const raw = sensor?.attributes?.slots
    if (Array.isArray(raw)) {
      // Attribute present — accept it as truth (including the legitimate
      // "all deleted" case where it's an empty array).
      this._lastSeenSlots = raw as ScheduleSlot[]
      return (raw as ScheduleSlot[])
        .slice()
        .sort((a, b) => a.hour * 60 + a.minute - (b.hour * 60 + b.minute))
    }
    // Attribute absent (unknown/unavailable state) — keep what we last
    // saw instead of flashing empty. Coordinator-side cache handles mid-
    // session partials, so this only fires before our first valid poll.
    return (this._lastSeenSlots ?? [])
      .slice()
      .sort((a, b) => a.hour * 60 + a.minute - (b.hour * 60 + b.minute))
  }

  /** Fingerprint a slot list for optimistic/sensor comparison. */
  private _slotsSignature(slots: ScheduleSlot[]): string {
    return slots
      .slice()
      .sort((a, b) => a.hour * 60 + a.minute - (b.hour * 60 + b.minute))
      .map((s) =>
        [
          s.hour,
          s.minute,
          s.portions,
          s.enabled ? 1 : 0,
          s.days.slice().sort().join(","),
        ].join(":"),
      )
      .join("|")
  }

  updated(changed: Map<string, unknown>): void {
    super.updated?.(changed)
    // Once the HA sensor value matches what we optimistically showed, we
    // can drop the override and let the real sensor drive the view again.
    if (this._optimisticSlots !== null && changed.has("hass")) {
      const sensor = this._s(this._config?.schedules_sensor)
      const raw = sensor?.attributes?.slots
      if (Array.isArray(raw)) {
        const sig = this._slotsSignature(raw as ScheduleSlot[])
        if (sig === this._slotsSignature(this._optimisticSlots)) {
          this._optimisticSlots = null
        }
      }
    }
  }

  private async _writeSchedules(slots: ScheduleSlot[]): Promise<void> {
    if (!this.hass || !this._config?.device_id) return
    // Flip the UI to the new list immediately; the sensor will confirm a
    // few hundred ms later and clear the override.
    this._optimisticSlots = slots
    try {
      await this.hass.callService("petlibro_lite", "schedule_set_all", {
        device_id: this._config.device_id,
        slots,
      })
    } catch (err) {
      // Service rejected — revert the optimistic view.
      this._optimisticSlots = null
      throw err
    }
  }

  private async _toggleSlot(index: number): Promise<void> {
    const schedules = this._schedules()
    const patched = schedules.map((s, i) =>
      i === index ? { ...s, enabled: !s.enabled } : s,
    )
    await this._writeSchedules(patched)
  }

  private async _deleteSlot(index: number): Promise<void> {
    const schedules = this._schedules()
    const patched = schedules.filter((_, i) => i !== index)
    await this._writeSchedules(patched)
  }

  private _startAdd(): void {
    this._editing = { mode: "add" }
    this._editDraft = {
      hour: 8,
      minute: 0,
      portions: 1,
      enabled: true,
      days: [...DAY_ORDER],
    }
  }

  private _startEdit(index: number): void {
    const slot = this._schedules()[index]
    if (!slot) return
    this._editing = { mode: "edit", index }
    this._editDraft = { ...slot, days: [...slot.days] }
  }

  private async _saveEdit(): Promise<void> {
    if (!this._editing || !this._editDraft || this._savingSchedule) return
    this._savingSchedule = true
    try {
      const schedules = this._schedules()
      let next: ScheduleSlot[]
      if (this._editing.mode === "add") {
        next = [...schedules, this._editDraft]
      } else {
        const idx = this._editing.index
        next = schedules.map((s, i) => (i === idx ? this._editDraft! : s))
      }
      await this._writeSchedules(next)
      this._editing = null
      this._editDraft = null
    } finally {
      this._savingSchedule = false
    }
  }

  private _updateDraft(patch: Partial<ScheduleSlot>): void {
    if (!this._editDraft) return
    this._editDraft = { ...this._editDraft, ...patch }
  }

  private _toggleDraftDay(day: string): void {
    if (!this._editDraft) return
    const set = new Set(this._editDraft.days)
    if (set.has(day)) set.delete(day)
    else set.add(day)
    this._editDraft = {
      ...this._editDraft,
      days: DAY_ORDER.filter((d) => set.has(d)),
    }
  }

  // ---------------------------------------------------------------- render

  render() {
    if (!this._config || !this.hass) return nothing

    const stateSensor = this._s(this._config.state_sensor)
    const foodLevel = this._s(this._config.food_level_sensor)
    const lastManual = this._s(this._config.last_manual_sensor)
    const lastScheduled = this._s(this._config.last_scheduled_sensor)
    const warning = this._s(this._config.warning_sensor)
    const camera = this._s(this._config.camera_entity)

    const name = this._config.name ?? "PetLibro Feeder"
    const isFeeding = stateSensor?.state === "feeding"
    const isOffline = stateSensor?.state === "unavailable"
    const foodState = foodLevel?.state ?? ""
    const warningState = warning?.state ?? "ok"
    const hasDeviceWarning = !WARNING_OK_STATES.has(warningState)

    let badge: { label: string; icon: string; sev: "warn" | "error" } | null = null
    if (isOffline) {
      badge = { label: "offline", icon: "mdi:cloud-off-outline", sev: "error" }
    } else if (foodState === "empty") {
      badge = { label: "out of food", icon: "mdi:bowl-outline", sev: "error" }
    } else if (hasDeviceWarning) {
      badge = {
        label: warningState.replace(/_/g, " "),
        icon: "mdi:alert-circle-outline",
        sev: warningState === "outlet_blocked" ? "error" : "warn",
      }
    } else if (foodState === "low") {
      badge = { label: "food low", icon: "mdi:bowl-outline", sev: "warn" }
    }

    const lastFed = this._latestFed(lastManual, lastScheduled)
    const portions = this._config.portions ?? [1, 2]

    const cameraThumbUrl = camera?.attributes
      ? (camera.attributes as Record<string, string>).entity_picture
      : undefined
    const streamState =
      (camera?.attributes as Record<string, string> | undefined)?.stream_state
    const isConnecting =
      !!streamState && CONNECTING_PHASES.has(streamState)

    const cardTappable = !!(this._config.feed_log_sensor ||
      this._config.schedules_sensor)

    return html`
      <ha-card>
        ${cameraThumbUrl
          ? html`
              <div
                class="camera-thumb"
                @click=${() => this._openMore(this._config!.camera_entity)}
                role="button"
                tabindex="0"
              >
                <img src=${cameraThumbUrl} alt="feeder camera" />
                ${isConnecting
                  ? html`
                      <div class="connecting-overlay">
                        <div class="spinner"></div>
                        <div class="connecting-text">
                          ${PHASE_LABEL[streamState!] ?? "Connecting…"}
                        </div>
                      </div>
                    `
                  : isFeeding
                    ? html`<div class="feeding-pill">
                        <ha-icon icon="mdi:paw"></ha-icon>Feeding
                      </div>`
                    : nothing}
              </div>
            `
          : nothing}
        <div class="header">
          <div class="name">
            <ha-icon icon="mdi:cat"></ha-icon>
            <span>${name}</span>
          </div>
          ${badge
            ? html`
                <div
                  class="badge ${badge.sev}"
                  @click=${() =>
                    this._openMore(
                      badge!.label === "offline"
                        ? this._config!.state_sensor
                        : badge!.label.startsWith("food") ||
                            badge!.label === "out of food"
                          ? this._config!.food_level_sensor
                          : this._config!.warning_sensor,
                    )}
                >
                  <ha-icon icon=${badge.icon}></ha-icon>
                  <span>${badge.label}</span>
                </div>
              `
            : nothing}
        </div>
        <div class="status-card ${isFeeding ? "feeding" : ""}">
          <ha-icon
            class="status-icon"
            icon=${isFeeding ? "mdi:silverware-clean" : "mdi:paw"}
          ></ha-icon>
          <div class="status-text">
            <div class="status-title">
              ${isFeeding ? "Dispensing now…" : "Ready"}
            </div>
            <div class="status-sub">
              ${isFeeding
                ? "Motor is running"
                : lastFed
                  ? html`Last fed
                      ${this._relativeTime(lastFed.iso)}${lastFed.portions
                        ? html` · <span class="portions"
                              >${lastFed.portions}p</span
                            >`
                        : nothing}
                      · ${lastFed.kind}`
                  : "No feeds recorded yet"}
            </div>
          </div>
        </div>
        ${this._renderGlance()}
        <div class="manual-feed">
          <div class="manual-feed-label">Manual Feed</div>
          ${this._customPortionsMode
            ? html`
                <div class="feed-row custom-portions">
                  <select
                    class="portion-select"
                    .value=${String(this._customPortionsValue)}
                    @change=${this._onCustomPortionsInput}
                  >
                    ${Array.from(
                      { length: MAX_CUSTOM_PORTIONS },
                      (_, i) => i + 1,
                    ).map(
                      (n) => html`
                        <option
                          value=${n}
                          ?selected=${n === this._customPortionsValue}
                        >
                          ${n} portion${n === 1 ? "" : "s"}
                        </option>
                      `,
                    )}
                  </select>
                  <button
                    class="pf-btn pf-btn-primary feed-submit"
                    ?disabled=${this._pendingPortions !== null || isOffline}
                    @click=${() => this._submitCustomPortions()}
                  >
                    ${this._pendingPortions !== null ? "Feeding…" : "Feed"}
                  </button>
                  <button
                    class="pf-btn pf-btn-outline portion-cancel"
                    @click=${() => this._cancelCustomPortions()}
                    title="Cancel"
                  >
                    <ha-icon icon="mdi:close"></ha-icon>
                  </button>
                </div>
              `
            : html`
                <div class="feed-row">
                  ${portions.map(
                    (p, i) => html`
                      <button
                        class="pf-btn ${i === 0
                          ? "pf-btn-primary"
                          : "pf-btn-outline"} ${this._pendingPortions === p
                          ? "pending"
                          : ""}"
                        ?disabled=${this._pendingPortions !== null || isOffline}
                        @click=${() => this._feed(p)}
                      >
                        ${this._pendingPortions === p
                          ? "Feeding…"
                          : `${p} portion${p === 1 ? "" : "s"}`}
                      </button>
                    `,
                  )}
                  <button
                    class="pf-btn pf-btn-outline portion-more"
                    ?disabled=${this._pendingPortions !== null || isOffline}
                    @click=${() => this._openCustomPortions()}
                    title="Custom portions (1–${MAX_CUSTOM_PORTIONS})"
                  >
                    &hellip;
                  </button>
                </div>
              `}
          <div class="manual-feed-hint">
            1 portion ≈ 10g · feeder rate-limits rapid requests
          </div>
        </div>
        ${cardTappable
          ? html`
              <div class="secondary-actions">
                ${this._config.feed_log_sensor
                  ? html`
                      <button
                        class="secondary-btn"
                        @click=${() => this._openDialog("log")}
                      >
                        <ha-icon icon="mdi:history"></ha-icon>
                        <span>Activity</span>
                      </button>
                    `
                  : nothing}
                ${this._config.schedules_sensor
                  ? html`
                      <button
                        class="secondary-btn"
                        @click=${() => this._openDialog("schedules")}
                      >
                        <ha-icon icon="mdi:clock-outline"></ha-icon>
                        <span>Schedules</span>
                      </button>
                    `
                  : nothing}
              </div>
            `
          : nothing}
      </ha-card>
      ${this._dialogMode ? this._renderDialog() : nothing}
    `
  }

  // ---------------------------------------------------------------- dialog

  private _renderDialog(): TemplateResult {
    const name = this._config?.name ?? "PetLibro Feeder"
    const mode = this._dialogMode
    const titleIcon =
      mode === "schedules" ? "mdi:clock-outline" : "mdi:history"
    const titleText =
      mode === "schedules"
        ? this._editing
          ? this._editing.mode === "add"
            ? "Add schedule"
            : "Edit schedule"
          : "Schedules"
        : "Activity"

    return html`
      <div
        class="dialog-scrim"
        @click=${(e: Event) => {
          if (e.target === e.currentTarget) this._closeDialog()
        }}
      >
        <div class="dialog">
          <div class="dialog-header">
            <div class="dialog-title">
              <ha-icon icon=${titleIcon}></ha-icon>
              <span>${titleText}</span>
              <span class="dialog-subtitle">${name}</span>
            </div>
            <button
              class="dialog-close"
              @click=${() => this._closeDialog()}
              title="Close"
            >
              <ha-icon icon="mdi:close"></ha-icon>
            </button>
          </div>
          ${mode === "schedules"
            ? this._editing
              ? this._renderEditor()
              : this._renderSchedules(
                  this._schedules(),
                  !!this._config?.device_id,
                )
            : this._renderLog(this._logEntries())}
        </div>
      </div>
    `
  }

  private _renderLog(log: LogEntry[]): TemplateResult {
    const rows = log.slice(0, 25).map((e) => this._describeLogEntry(e))
    return html`
      <div class="section">
        ${log.length === 0
          ? html`<div class="empty">No recent feed events</div>`
          : html`
              <ul class="log">
                ${rows.map(
                  (row) => html`
                    <li class=${row.severity}>
                      <ha-icon icon=${row.icon}></ha-icon>
                      <span class="log-primary">${row.label}</span>
                      <span class="log-time">${row.timeLabel}</span>
                    </li>
                  `,
                )}
              </ul>
            `}
      </div>
    `
  }

  private _describeLogEntry(e: LogEntry): {
    icon: string
    label: string
    severity: "feed" | "scheduled" | "warn"
    timeLabel: string
  } {
    const timeLabel = this._relativeTime(e.time)
    if (e.kind === "warning") {
      const label =
        e.code != null
          ? WARNING_CODE_LABEL[e.code] ?? `Warning (code ${e.code})`
          : "Warning"
      return { icon: "mdi:alert-circle-outline", label, severity: "warn", timeLabel }
    }
    // Manual / scheduled feed. portions == 0 means the feeder tried to
    // dispense but nothing came out (e.g., outlet blocked). Surface that
    // distinctly so history shows actionable failures, not silent zeros.
    const portions = e.portions ?? 0
    if (portions === 0) {
      return {
        icon: "mdi:alert-circle-outline",
        label: "Feed attempt — 0 dispensed",
        severity: "warn",
        timeLabel,
      }
    }
    if (e.kind === "scheduled") {
      return {
        icon: "mdi:clock-outline",
        label: `Scheduled feed · ${portions}p`,
        severity: "scheduled",
        timeLabel,
      }
    }
    return {
      icon: "mdi:paw",
      label: `Fed manually · ${portions}p`,
      severity: "feed",
      timeLabel,
    }
  }

  private _renderSchedules(
    schedules: ScheduleSlot[],
    canEdit: boolean,
  ): TemplateResult {
    return html`
      <div class="section">
        ${canEdit
          ? html`
              <div class="section-toolbar">
                <button
                  class="add-btn"
                  @click=${() => this._startAdd()}
                  title="Add a scheduled feed"
                >
                  <ha-icon icon="mdi:plus"></ha-icon>Add schedule
                </button>
              </div>
            `
          : nothing}
        ${schedules.length === 0
          ? html`<div class="empty">No schedules configured</div>`
          : html`
              <ul class="schedules">
                ${schedules.map(
                  (s, i) => html`
                    <li class=${s.enabled ? "enabled" : "disabled"}>
                      <div class="sched-time">${formatHMDisplay(s.hour, s.minute)}</div>
                      <div class="sched-meta">
                        <div class="sched-days">${formatDays(s.days)}</div>
                        <div class="sched-portions">
                          ${s.portions} portion${s.portions === 1 ? "" : "s"}
                        </div>
                      </div>
                      ${canEdit
                        ? html`
                            <button
                              class="icon-btn"
                              title=${s.enabled ? "Disable" : "Enable"}
                              @click=${() => this._toggleSlot(i)}
                            >
                              <ha-icon
                                icon=${s.enabled
                                  ? "mdi:toggle-switch"
                                  : "mdi:toggle-switch-off-outline"}
                              ></ha-icon>
                            </button>
                            <button
                              class="icon-btn"
                              title="Edit"
                              @click=${() => this._startEdit(i)}
                            >
                              <ha-icon icon="mdi:pencil"></ha-icon>
                            </button>
                            <button
                              class="icon-btn danger"
                              title="Delete"
                              @click=${() => this._deleteSlot(i)}
                            >
                              <ha-icon icon="mdi:trash-can-outline"></ha-icon>
                            </button>
                          `
                        : nothing}
                    </li>
                  `,
                )}
              </ul>
            `}
      </div>
    `
  }

  private _renderEditor(): TemplateResult {
    if (!this._editDraft) return html``
    const draft = this._editDraft
    const isAdd = this._editing?.mode === "add"
    const canSave =
      draft.days.length > 0 &&
      draft.portions >= 1 &&
      draft.portions <= 50 &&
      !this._savingSchedule
    return html`
      <div class="section editor">
        <div class="editor-row">
          <label>Time</label>
          <input
            class="time-input"
            type="time"
            .value=${formatHM(draft.hour, draft.minute)}
            @change=${(e: InputEvent) => {
              const [h, m] = (e.target as HTMLInputElement).value.split(":")
              this._updateDraft({
                hour: Number(h) || 0,
                minute: Number(m) || 0,
              })
            }}
          />
        </div>
        <div class="editor-row">
          <label>Portions</label>
          <div class="stepper">
            <button
              class="icon-btn"
              @click=${() =>
                this._updateDraft({
                  portions: Math.max(1, draft.portions - 1),
                })}
              ?disabled=${draft.portions <= 1}
            >
              <ha-icon icon="mdi:minus"></ha-icon>
            </button>
            <div class="stepper-value">${draft.portions}</div>
            <button
              class="icon-btn"
              @click=${() =>
                this._updateDraft({
                  portions: Math.min(50, draft.portions + 1),
                })}
              ?disabled=${draft.portions >= 50}
            >
              <ha-icon icon="mdi:plus"></ha-icon>
            </button>
          </div>
        </div>
        <div class="editor-row">
          <label>Days</label>
          <div class="day-chips">
            ${DAY_ORDER.map((d, i) => {
              const active = draft.days.includes(d)
              return html`
                <button
                  class="day-chip ${active ? "active" : ""}"
                  @click=${() => this._toggleDraftDay(d)}
                  title=${d}
                >
                  ${DAY_LABEL[d]}<sub>${i + 1}</sub>
                </button>
              `
            })}
          </div>
        </div>
        <div class="editor-row">
          <label>Enabled</label>
          <button
            class="icon-btn big"
            @click=${() => this._updateDraft({ enabled: !draft.enabled })}
          >
            <ha-icon
              icon=${draft.enabled
                ? "mdi:toggle-switch"
                : "mdi:toggle-switch-off-outline"}
            ></ha-icon>
          </button>
        </div>
        <div class="editor-actions">
          <button
            class="btn ghost"
            @click=${() => {
              this._editing = null
              this._editDraft = null
            }}
          >
            Cancel
          </button>
          <button
            class="btn primary"
            ?disabled=${!canSave}
            @click=${() => this._saveEdit()}
          >
            ${this._savingSchedule ? "Saving…" : isAdd ? "Add" : "Save"}
          </button>
        </div>
      </div>
    `
  }

  static styles = css`
    :host {
      --petlibro-accent: var(--primary-color, #03a9f4);
      --petlibro-warn: var(--warning-color, #ff9800);
      --petlibro-error: var(--error-color, #e45353);
    }
    ha-card {
      padding: 14px 16px;
      display: flex;
      flex-direction: column;
      gap: 10px;
    }
    .camera-thumb {
      margin: -14px -16px 4px;
      position: relative;
      cursor: pointer;
      background: var(--card-background-color, #000);
      overflow: hidden;
    }
    .camera-thumb img {
      display: block;
      width: 100%;
      height: auto;
      aspect-ratio: 16 / 9;
      object-fit: cover;
    }
    .connecting-overlay {
      position: absolute;
      inset: 0;
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      gap: 10px;
      background: rgba(0, 0, 0, 0.55);
      color: #fff;
      backdrop-filter: blur(4px);
    }
    .spinner {
      width: 28px;
      height: 28px;
      border: 3px solid rgba(255, 255, 255, 0.25);
      border-top-color: #fff;
      border-radius: 50%;
      animation: spin 0.9s linear infinite;
    }
    @keyframes spin {
      to {
        transform: rotate(360deg);
      }
    }
    .connecting-text {
      font-size: 13px;
      font-weight: 500;
      letter-spacing: 0.02em;
    }
    .feeding-pill {
      position: absolute;
      top: 8px;
      left: 8px;
      display: inline-flex;
      align-items: center;
      gap: 4px;
      padding: 3px 10px;
      font-size: 12px;
      font-weight: 500;
      background: rgba(0, 0, 0, 0.55);
      color: #fff;
      border-radius: 999px;
      backdrop-filter: blur(6px);
    }
    .feeding-pill ha-icon {
      --mdc-icon-size: 14px;
    }
    .header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 8px;
    }
    .name {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      font-size: 16px;
      font-weight: 500;
      color: var(--primary-text-color);
    }
    .name ha-icon {
      --mdc-icon-size: 20px;
      color: var(--petlibro-accent);
    }
    .badge {
      display: inline-flex;
      align-items: center;
      gap: 4px;
      padding: 3px 10px;
      font-size: 12px;
      font-weight: 500;
      color: #fff;
      border-radius: 999px;
      cursor: pointer;
      white-space: nowrap;
    }
    .badge.warn {
      background: var(--petlibro-warn);
    }
    .badge.error {
      background: var(--petlibro-error);
    }
    .badge ha-icon {
      --mdc-icon-size: 14px;
    }
    /* Status card: mirror the React dashboard's status row.
       Muted background, icon left, title + subtitle stacked. */
    .status-card {
      display: flex;
      align-items: center;
      gap: 12px;
      padding: 12px;
      border-radius: 12px;
      background: color-mix(in srgb, var(--divider-color, #d0d0d0) 30%, transparent);
    }
    .status-card .status-icon {
      --mdc-icon-size: 22px;
      color: var(--secondary-text-color);
      flex-shrink: 0;
    }
    .status-card.feeding .status-icon {
      color: var(--petlibro-accent);
      animation: pf-pulse 1.3s ease-in-out infinite;
    }
    @keyframes pf-pulse {
      0%, 100% { opacity: 1; }
      50% { opacity: 0.45; }
    }
    .status-text {
      flex: 1;
      min-width: 0;
    }
    .status-title {
      font-size: 14px;
      font-weight: 500;
      color: var(--primary-text-color);
    }
    .status-sub {
      font-size: 12px;
      color: var(--secondary-text-color);
      margin-top: 1px;
    }
    /* Glance strip: compact "Next feed" / "Today" summary between the
       status card and Manual Feed section. Two-up grid that collapses
       gracefully when only one sensor is wired. */
    .glance {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(0, 1fr));
      gap: 8px;
    }
    .glance-item {
      display: flex;
      align-items: center;
      gap: 10px;
      padding: 10px 12px;
      border-radius: 10px;
      background: color-mix(in srgb, var(--divider-color, #d0d0d0) 18%, transparent);
      cursor: pointer;
      transition: background 0.15s ease;
    }
    .glance-item:hover {
      background: color-mix(in srgb, var(--divider-color, #d0d0d0) 32%, transparent);
    }
    .glance-item ha-icon {
      --mdc-icon-size: 18px;
      color: var(--secondary-text-color);
      flex-shrink: 0;
    }
    .glance-text {
      min-width: 0;
    }
    .glance-label {
      font-size: 11px;
      color: var(--secondary-text-color);
      text-transform: uppercase;
      letter-spacing: 0.4px;
    }
    .glance-value {
      font-size: 14px;
      color: var(--primary-text-color);
      font-weight: 500;
      margin-top: 2px;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }
    .glance-value .portions {
      color: var(--petlibro-accent);
      font-weight: 600;
    }
    .glance-value .glance-unit {
      color: var(--secondary-text-color);
      font-size: 12px;
      font-weight: 400;
      margin-left: 2px;
    }
    .status-sub .portions {
      color: var(--primary-text-color);
      font-weight: 500;
    }
    /* Legacy .last-fed style kept for the dialog feed log. */
    .last-fed {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      font-size: 13px;
      color: var(--secondary-text-color);
    }
    .last-fed ha-icon {
      --mdc-icon-size: 15px;
      color: var(--petlibro-accent);
    }
    .last-fed .portions {
      color: var(--primary-text-color);
      font-weight: 500;
    }
    .last-fed .kind {
      margin-left: auto;
      font-size: 11px;
      text-transform: uppercase;
      letter-spacing: 0.04em;
      color: var(--secondary-text-color);
      opacity: 0.75;
    }
    .manual-feed {
      display: flex;
      flex-direction: column;
      gap: 6px;
    }
    .manual-feed-label {
      padding: 0 4px;
      font-size: 13px;
      font-weight: 500;
      color: var(--secondary-text-color);
    }
    .manual-feed-hint {
      padding: 0 4px;
      font-size: 11px;
      color: var(--secondary-text-color);
    }
    .feed-row {
      display: flex;
      gap: 8px;
    }
    .feed-row > .pf-btn {
      flex: 1;
      min-width: 0;
    }
    .secondary-actions {
      display: flex;
      gap: 8px;
      margin-top: 2px;
    }
    .secondary-btn {
      flex: 1;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      gap: 6px;
      padding: 8px 10px;
      border: 1px solid var(--divider-color, #d0d0d0);
      background: var(--card-background-color, #fff);
      color: var(--primary-text-color);
      border-radius: 10px;
      font-size: 13px;
      font-weight: 500;
      cursor: pointer;
      transition:
        background 0.15s,
        border-color 0.15s;
    }
    .secondary-btn:hover {
      background: var(--secondary-background-color, #f3f3f3);
      border-color: var(--petlibro-accent);
    }
    .secondary-btn ha-icon {
      --mdc-icon-size: 16px;
      color: var(--petlibro-accent);
    }
    /* shadcn-Button-flavored portion buttons: one primary, rest outline.
       Matches the React dashboard's Manual Feed row — a single fluent
       label per button ("1 portion", "2 portions", …), not count/unit
       stacked. Pending state swaps label to "Feeding…". */
    .pf-btn {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      gap: 6px;
      height: 38px;
      padding: 0 14px;
      border-radius: 8px;
      border: 1px solid transparent;
      font-size: 13px;
      font-weight: 500;
      line-height: 1;
      cursor: pointer;
      font-family: inherit;
      transition:
        background 0.15s,
        border-color 0.15s,
        opacity 0.15s;
    }
    .pf-btn:disabled {
      opacity: 0.5;
      cursor: default;
    }
    .pf-btn-primary {
      background: var(--petlibro-accent);
      border-color: var(--petlibro-accent);
      color: #fff;
    }
    .pf-btn-primary:hover:not(:disabled) {
      background: color-mix(in srgb, var(--petlibro-accent) 88%, #000);
      border-color: color-mix(in srgb, var(--petlibro-accent) 88%, #000);
    }
    .pf-btn-outline {
      background: transparent;
      border-color: var(--divider-color, #d0d0d0);
      color: var(--primary-text-color);
    }
    .pf-btn-outline:hover:not(:disabled) {
      background: var(--secondary-background-color, #f3f3f3);
    }
    .pf-btn.pending {
      background: color-mix(in srgb, var(--petlibro-accent) 18%, transparent);
      border-color: var(--petlibro-accent);
      color: var(--petlibro-accent);
    }
    .portion-more {
      flex: 0 0 44px !important;
      padding: 0;
      font-size: 18px;
      letter-spacing: 0.05em;
    }
    .portion-cancel {
      flex: 0 0 38px !important;
      padding: 0;
    }
    .portion-cancel ha-icon {
      --mdc-icon-size: 18px;
    }
    .feed-row.custom-portions {
      align-items: stretch;
    }
    .portion-input {
      flex: 1;
      min-width: 0;
      height: 38px;
      font-size: 14px;
      font-weight: 500;
      text-align: center;
      padding: 0 10px;
      border: 1px solid var(--divider-color, #d0d0d0);
      border-radius: 8px;
      background: var(--card-background-color, #fff);
      color: var(--primary-text-color);
      font-family: inherit;
      -moz-appearance: textfield;
    }
    /* Native <select> — on iOS this renders as a wheel picker (matching the
       time input in the schedule edit form); desktop browsers show a
       dropdown. Styled to visually match pf-btn for consistency. */
    .portion-select {
      flex: 1;
      min-width: 0;
      height: 38px;
      font-size: 14px;
      font-weight: 500;
      padding: 0 12px;
      border: 1px solid var(--divider-color, #d0d0d0);
      border-radius: 8px;
      background: var(--card-background-color, #fff);
      color: var(--primary-text-color);
      font-family: inherit;
      cursor: pointer;
      appearance: menulist;
    }
    .portion-select:focus {
      outline: none;
      border-color: var(--petlibro-accent);
      box-shadow: 0 0 0 2px color-mix(in srgb, var(--petlibro-accent) 20%, transparent);
    }
    .portion-input:focus {
      outline: none;
      border-color: var(--petlibro-accent);
      box-shadow: 0 0 0 2px color-mix(in srgb, var(--petlibro-accent) 20%, transparent);
    }
    .portion-input::-webkit-outer-spin-button,
    .portion-input::-webkit-inner-spin-button {
      -webkit-appearance: none;
      margin: 0;
    }
    /* ------------------------------ dialog ------------------------------ */
    .dialog-scrim {
      position: fixed;
      inset: 0;
      z-index: 9999;
      background: rgba(0, 0, 0, 0.45);
      display: flex;
      align-items: center;
      justify-content: center;
      padding: 16px;
    }
    .dialog {
      width: 100%;
      max-width: 480px;
      max-height: calc(100vh - 48px);
      overflow: auto;
      background: var(--card-background-color, #fff);
      color: var(--primary-text-color);
      border-radius: 16px;
      box-shadow: 0 20px 60px rgba(0, 0, 0, 0.35);
      padding: 16px;
      display: flex;
      flex-direction: column;
      gap: 14px;
    }
    .dialog-header {
      display: flex;
      align-items: center;
      justify-content: space-between;
    }
    .dialog-title {
      display: inline-flex;
      align-items: baseline;
      gap: 8px;
      font-size: 18px;
      font-weight: 500;
    }
    .dialog-title ha-icon {
      --mdc-icon-size: 22px;
      color: var(--petlibro-accent);
      position: relative;
      top: 4px;
    }
    .dialog-subtitle {
      font-size: 13px;
      font-weight: 400;
      color: var(--secondary-text-color);
      margin-left: 2px;
    }
    .dialog-close {
      background: none;
      border: none;
      cursor: pointer;
      color: var(--secondary-text-color);
      padding: 4px;
    }
    .section {
      display: flex;
      flex-direction: column;
      gap: 8px;
    }
    .section-toolbar {
      display: flex;
      justify-content: flex-end;
    }
    .add-btn {
      display: inline-flex;
      align-items: center;
      gap: 4px;
      padding: 4px 10px;
      border: 1px solid var(--divider-color, #d0d0d0);
      background: var(--card-background-color);
      color: var(--primary-text-color);
      border-radius: 999px;
      font-size: 12px;
      font-weight: 500;
      cursor: pointer;
    }
    .add-btn ha-icon {
      --mdc-icon-size: 14px;
    }
    .empty {
      padding: 12px;
      text-align: center;
      color: var(--secondary-text-color);
      font-size: 13px;
      font-style: italic;
    }
    .log {
      list-style: none;
      padding: 0;
      margin: 0;
      display: flex;
      flex-direction: column;
      gap: 6px;
    }
    .log li {
      display: flex;
      align-items: center;
      gap: 8px;
      padding: 6px 10px;
      background: var(--secondary-background-color, #f5f5f5);
      border-radius: 8px;
      font-size: 13px;
    }
    .log li.warn {
      background: color-mix(in srgb, var(--petlibro-warn) 18%, transparent);
    }
    .log li ha-icon {
      --mdc-icon-size: 16px;
      color: var(--petlibro-accent);
    }
    .log li.warn ha-icon {
      color: var(--petlibro-warn);
    }
    .log-primary {
      color: var(--primary-text-color);
    }
    .log-time {
      margin-left: auto;
      color: var(--secondary-text-color);
      font-size: 12px;
    }
    .schedules {
      list-style: none;
      padding: 0;
      margin: 0;
      display: flex;
      flex-direction: column;
      gap: 6px;
    }
    .schedules li {
      display: grid;
      grid-template-columns: auto 1fr auto auto auto;
      align-items: center;
      gap: 10px;
      padding: 10px 12px 10px 14px;
      border-radius: 10px;
      border-left: 3px solid transparent;
      transition: background 0.15s, border-color 0.15s, opacity 0.15s;
    }
    .schedules li.enabled {
      background: color-mix(
        in srgb,
        var(--petlibro-accent) 14%,
        var(--card-background-color, #fff)
      );
      border-left-color: var(--petlibro-accent);
    }
    .schedules li.enabled .sched-time {
      color: var(--petlibro-accent);
    }
    .schedules li.disabled {
      background: var(--secondary-background-color, #f5f5f5);
      opacity: 0.6;
      filter: grayscale(0.3);
    }
    .schedules li.disabled .sched-time,
    .schedules li.disabled .sched-portions {
      text-decoration: line-through;
      text-decoration-color: color-mix(
        in srgb, var(--secondary-text-color) 50%, transparent
      );
    }
    .sched-time {
      font-size: 18px;
      font-weight: 600;
      font-variant-numeric: tabular-nums;
    }
    .sched-meta {
      display: flex;
      flex-direction: column;
      gap: 2px;
      font-size: 12px;
      color: var(--secondary-text-color);
    }
    .sched-meta .sched-portions {
      color: var(--primary-text-color);
    }
    .icon-btn {
      background: none;
      border: none;
      cursor: pointer;
      color: var(--secondary-text-color);
      padding: 4px;
      border-radius: 6px;
    }
    .icon-btn:hover:not(:disabled) {
      background: rgba(0, 0, 0, 0.06);
      color: var(--primary-text-color);
    }
    .icon-btn:disabled {
      opacity: 0.4;
      cursor: default;
    }
    .icon-btn.danger:hover {
      color: var(--petlibro-error);
    }
    .icon-btn.big ha-icon {
      --mdc-icon-size: 28px;
    }
    /* editor */
    .editor {
      gap: 14px;
    }
    .editor-row {
      display: flex;
      align-items: center;
      gap: 12px;
    }
    .editor-row label {
      flex: 0 0 80px;
      font-size: 13px;
      color: var(--secondary-text-color);
    }
    .time-input {
      flex: 1;
      padding: 8px 10px;
      font-size: 16px;
      border: 1px solid var(--divider-color, #d0d0d0);
      border-radius: 8px;
      background: var(--card-background-color);
      color: var(--primary-text-color);
    }
    .stepper {
      display: inline-flex;
      align-items: center;
      gap: 6px;
    }
    .stepper-value {
      min-width: 32px;
      text-align: center;
      font-size: 16px;
      font-weight: 500;
    }
    .day-chips {
      display: flex;
      gap: 4px;
      flex-wrap: wrap;
    }
    .day-chip {
      width: 32px;
      height: 32px;
      border-radius: 999px;
      border: 1px solid var(--divider-color, #d0d0d0);
      background: var(--card-background-color);
      color: var(--primary-text-color);
      font-size: 13px;
      font-weight: 500;
      cursor: pointer;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      position: relative;
    }
    .day-chip sub {
      display: none;
    }
    .day-chip.active {
      background: var(--petlibro-accent);
      color: #fff;
      border-color: var(--petlibro-accent);
    }
    .editor-actions {
      display: flex;
      gap: 8px;
      justify-content: flex-end;
      margin-top: 6px;
    }
    .btn {
      padding: 8px 16px;
      border-radius: 8px;
      font-size: 14px;
      font-weight: 500;
      cursor: pointer;
      border: 1px solid transparent;
    }
    .btn.ghost {
      background: none;
      color: var(--secondary-text-color);
      border-color: var(--divider-color, #d0d0d0);
    }
    .btn.primary {
      background: var(--petlibro-accent);
      color: #fff;
    }
    .btn:disabled {
      opacity: 0.5;
      cursor: default;
    }
  `
}

declare global {
  interface Window {
    customCards?: Array<{
      type: string
      name: string
      description: string
      preview?: boolean
    }>
  }
}

window.customCards = window.customCards ?? []
window.customCards.push({
  type: "petlibro-feeder-card",
  name: "PetLibro Feeder",
  description:
    "Status, last-fed, portion feeding, feed log, and schedule editor for a PetLibro feeder.",
  preview: false,
})

// eslint-disable-next-line no-console
console.info(
  "%c petlibro-feeder-card %c 0.1.0 ",
  "background:#03a9f4;color:#fff;padding:2px 4px;border-radius:2px 0 0 2px",
  "background:#333;color:#fff;padding:2px 4px;border-radius:0 2px 2px 0",
)
