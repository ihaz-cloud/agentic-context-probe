#!/bin/bash
# =============================================================================
# token-tracking.sh — Phase-aware token tracking per work item
# =============================================================================
#
# PURPOSE
#   Measures API token consumption per bead per phase by bookmarking transcript
#   line offsets. Supports individual bead work (--bead) and batch coordination
#   (--coordinate). Tracks across sessions with per-session segment nesting.
#
# COMMANDS
#   start   --bead <id> --phase <phase> --session <sid>
#   start   --coordinate --beads <id1,id2,...> --session <sid>
#   stop    --bead <id> [--json]
#   stop    --coordinate --session <sid> [--json]
#   status  --bead <id> [--json]
#   status  --coordinate --session <sid> [--json]
#   list
#
# MODES
#   --bead <id>         Individual bead work. Requires --phase on start.
#   --coordinate        Batch planning. Requires --beads on start. Phase is
#                       always "coordinate" (set internally).
#
# PHASES (--bead mode only)
#   plan, discover, implement, test, fix
#
# RULES
#   - Only one tracking active at a time (single-active enforcement)
#   - Phase transitions require explicit stop + start
#   - Resume: start with same bead + same phase + same session = bank + continue
#   - Orphan: start with same bead + same phase + different session = mark orphaned
#   - --coordinate and --bead are mutually exclusive
#
# STORAGE
#   Per-bead:        ~/.claude/.token_tracking/<bead-id>.json
#   Per-coordinate:  ~/.claude/.token_tracking/coordinate.<session-id>.json
#
# =============================================================================
set -uo pipefail

TRACK_DIR="$HOME/.claude/.token_tracking"
mkdir -p "$TRACK_DIR"

# NOTE: 'coordinate' is intentionally NOT in VALID_PHASES. The coordinate phase
# is set internally via the --coordinate flag, not via --phase coordinate. The
# schema enum DOES list 'coordinate' because metrics records can have
# phase: coordinate after coordinate-phase tracking flushes — but users invoking
# this script should use --coordinate, not --phase coordinate.
VALID_PHASES=("plan" "discover" "implement" "test" "fix")

# -----------------------------------------------------------------------------
# Argument parsing
# -----------------------------------------------------------------------------
ACTION="${1:-}"
shift 2>/dev/null || true

BEAD_ID=""
BEADS_LIST=""
PHASE=""
SESSION_ID=""
COORDINATE=false
JSON_OUTPUT=false

while [[ $# -gt 0 ]]; do
    case "$1" in
        --bead)     BEAD_ID="$2"; shift 2 ;;
        --beads)    BEADS_LIST="$2"; shift 2 ;;
        --phase)    PHASE="$2"; shift 2 ;;
        --session)  SESSION_ID="$2"; shift 2 ;;
        --coordinate) COORDINATE=true; shift ;;
        --json)     JSON_OUTPUT=true; shift ;;
        *) echo "Error: Unknown argument '$1'"; exit 1 ;;
    esac
done

# -----------------------------------------------------------------------------
# Validation helpers
# -----------------------------------------------------------------------------
validate_phase() {
    local p="$1"
    for v in "${VALID_PHASES[@]}"; do
        [[ "$v" == "$p" ]] && return 0
    done
    echo "Error: Invalid phase '$p'. Valid: ${VALID_PHASES[*]}"
    exit 1
}

validate_mode() {
    if $COORDINATE && [[ -n "$BEAD_ID" ]]; then
        echo "Error: --bead and --coordinate are mutually exclusive."
        exit 1
    fi
    if $COORDINATE && [[ -z "$BEADS_LIST" ]]; then
        echo "Error: --coordinate requires --beads <id1,id2,...>."
        exit 1
    fi
    if [[ -n "$BEADS_LIST" ]] && ! $COORDINATE; then
        echo "Error: --beads requires --coordinate flag."
        exit 1
    fi
    if ! $COORDINATE && [[ -z "$BEAD_ID" ]]; then
        echo "Error: Specify --bead <id> or --coordinate --beads <id1,id2,...>."
        exit 1
    fi
    if [[ -n "$BEAD_ID" ]] && [[ "$BEAD_ID" == *","* ]]; then
        echo "Error: --bead accepts a single bead ID. For multiple beads use --coordinate --beads <id1,id2,...>."
        exit 1
    fi
}

resolve_transcript() {
    local sid="$1"
    local found
    found=$(ls "$HOME"/.claude/projects/*/"${sid}.jsonl" 2>/dev/null | head -1)
    if [[ -z "$found" ]]; then
        echo "Error: No transcript found for session '$sid'."
        exit 1
    fi
    echo "$found"
}

# -----------------------------------------------------------------------------
# JSON helpers (using jq)
# -----------------------------------------------------------------------------
get_line_count() {
    wc -l < "$1"
}

sum_tokens() {
    local file="$1" start_line="$2" end_line="$3"
    sed -n "${start_line},${end_line}p" "$file" | jq -c '
        select(.type == "assistant" and .message.usage != null)
        | .message.usage
    ' 2>/dev/null | jq -s '{
        input_tokens: (map(.input_tokens // 0) | add // 0),
        cache_read_tokens: (map(.cache_read_input_tokens // 0) | add // 0),
        cache_create_tokens: (map(.cache_creation_input_tokens // 0) | add // 0),
        output_tokens: (map(.output_tokens // 0) | add // 0),
        turns: length
    }'
}

# Read a field from a JSON track file
jq_read() {
    jq -r "$1" "$2" 2>/dev/null
}

# Check if ANY tracking is active (single-active enforcement)
check_single_active() {
    local skip_file="${1:-}"
    for f in "$TRACK_DIR"/*.json; do
        [[ -f "$f" ]] || continue
        [[ "$f" == "$skip_file" ]] && continue
        local ap
        ap=$(jq_read '.active_phase // .active // empty' "$f")
        if [[ -n "$ap" && "$ap" != "null" && "$ap" != "false" ]]; then
            local wid
            wid=$(jq_read '.work_id // .type' "$f")
            echo "Error: '$wid' is active (phase: $ap). Run 'stop' on it first."
            exit 1
        fi
    done
}

# -----------------------------------------------------------------------------
# start --bead
# -----------------------------------------------------------------------------
start_bead() {
    [[ -z "$PHASE" ]] && { echo "Error: --phase is required for start --bead."; exit 1; }
    [[ -z "$SESSION_ID" ]] && { echo "Error: --session is required for start."; exit 1; }
    validate_phase "$PHASE"

    local transcript
    transcript=$(resolve_transcript "$SESSION_ID")
    local track_file="$TRACK_DIR/${BEAD_ID}.json"
    local now
    now=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
    local current_line
    current_line=$(get_line_count "$transcript")

    if [[ ! -f "$track_file" ]]; then
        # Fresh start — no track file
        check_single_active ""
        jq -n \
            --arg wid "$BEAD_ID" \
            --arg sid "$SESSION_ID" \
            --arg phase "$PHASE" \
            --arg transcript "$transcript" \
            --argjson bookmark "$current_line" \
            --arg started "$now" \
            '{
                work_id: $wid,
                active_session: $sid,
                active_phase: $phase,
                active_started: $started,
                bookmark: $bookmark,
                sessions: {
                    ($sid): {
                        transcript: $transcript,
                        segments: []
                    }
                }
            }' > "$track_file"
        echo "Started tracking $BEAD_ID phase=$PHASE session=$SESSION_ID at line $current_line"
        return
    fi

    # Track file exists
    local active_phase active_session
    active_phase=$(jq_read '.active_phase // empty' "$track_file")
    active_session=$(jq_read '.active_session // empty' "$track_file")

    if [[ -z "$active_phase" || "$active_phase" == "null" ]]; then
        # No active phase — open new segment after previous stop
        check_single_active "$track_file"
        local tmp
        tmp=$(jq \
            --arg sid "$SESSION_ID" \
            --arg phase "$PHASE" \
            --arg transcript "$transcript" \
            --argjson bookmark "$current_line" \
            --arg started "$now" \
            '
            .active_session = $sid |
            .active_phase = $phase |
            .active_started = $started |
            .bookmark = $bookmark |
            if .sessions[$sid] then . else .sessions[$sid] = {transcript: $transcript, segments: []} end
            ' "$track_file")
        echo "$tmp" > "$track_file"
        echo "Started tracking $BEAD_ID phase=$PHASE session=$SESSION_ID at line $current_line"
        return
    fi

    if [[ "$active_phase" == "$PHASE" && "$active_session" == "$SESSION_ID" ]]; then
        # Resume — same bead, same phase, same session (compaction)
        local old_bookmark
        old_bookmark=$(jq_read '.bookmark' "$track_file")
        local old_transcript
        old_transcript=$(jq_read ".sessions[\"$SESSION_ID\"].transcript" "$track_file")

        if [[ -f "$old_transcript" && "$old_bookmark" -lt "$current_line" ]]; then
            # Bank tokens from old bookmark to current line
            local seg_tokens
            seg_tokens=$(sum_tokens "$old_transcript" "$((old_bookmark + 1))" "$current_line")

            local tmp
            tmp=$(jq \
                --argjson bookmark "$current_line" \
                --argjson seg "$seg_tokens" \
                '
                .bookmark = $bookmark |
                .sessions[.active_session].banked_input = ((.sessions[.active_session].banked_input // 0) + $seg.input_tokens) |
                .sessions[.active_session].banked_cache_read = ((.sessions[.active_session].banked_cache_read // 0) + $seg.cache_read_tokens) |
                .sessions[.active_session].banked_cache_create = ((.sessions[.active_session].banked_cache_create // 0) + $seg.cache_create_tokens) |
                .sessions[.active_session].banked_output = ((.sessions[.active_session].banked_output // 0) + $seg.output_tokens) |
                .sessions[.active_session].banked_turns = ((.sessions[.active_session].banked_turns // 0) + $seg.turns)
                ' "$track_file")
            echo "$tmp" > "$track_file"
        fi

        # Update transcript path (may have changed on compaction) and bookmark
        local tmp
        tmp=$(jq \
            --arg transcript "$transcript" \
            --argjson bookmark "$current_line" \
            '
            .bookmark = $bookmark |
            .sessions[.active_session].transcript = $transcript
            ' "$track_file")
        echo "$tmp" > "$track_file"
        echo "Resumed tracking $BEAD_ID phase=$PHASE session=$SESSION_ID at line $current_line"
        return
    fi

    if [[ "$active_phase" == "$PHASE" && "$active_session" != "$SESSION_ID" ]]; then
        # Orphan recovery — same phase, different session
        local old_bookmark old_transcript
        old_bookmark=$(jq_read '.bookmark' "$track_file")
        old_transcript=$(jq_read ".sessions[\"$active_session\"].transcript" "$track_file")
        local orphan_now
        orphan_now=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

        # Try to bank remaining tokens from old transcript
        local orphan_tokens='{"input_tokens":0,"cache_read_tokens":0,"cache_create_tokens":0,"output_tokens":0,"turns":0}'
        if [[ -f "$old_transcript" ]]; then
            local old_end
            old_end=$(get_line_count "$old_transcript")
            if [[ "$old_bookmark" -lt "$old_end" ]]; then
                orphan_tokens=$(sum_tokens "$old_transcript" "$((old_bookmark + 1))" "$old_end")
            fi
        fi

        # Add banked tokens to orphan segment
        local tmp
        tmp=$(jq \
            --arg phase "$active_phase" \
            --arg stopped "$orphan_now" \
            --arg old_sid "$active_session" \
            --argjson seg "$orphan_tokens" \
            '
            .sessions[$old_sid].segments += [{
                phase: $phase,
                started: (.active_started // "unknown"),
                stopped: $stopped,
                input_tokens: ((.sessions[$old_sid].banked_input // 0) + $seg.input_tokens),
                cache_read_tokens: ((.sessions[$old_sid].banked_cache_read // 0) + $seg.cache_read_tokens),
                cache_create_tokens: ((.sessions[$old_sid].banked_cache_create // 0) + $seg.cache_create_tokens),
                output_tokens: ((.sessions[$old_sid].banked_output // 0) + $seg.output_tokens),
                turns: ((.sessions[$old_sid].banked_turns // 0) + $seg.turns),
                orphaned: true,
                orphan_reason: "session ended without stop"
            }] |
            del(.sessions[$old_sid].banked_input, .sessions[$old_sid].banked_cache_read,
                .sessions[$old_sid].banked_cache_create, .sessions[$old_sid].banked_output,
                .sessions[$old_sid].banked_turns)
            ' "$track_file")
        echo "$tmp" > "$track_file"

        echo "Warning: Orphaned segment from session $active_session (phase=$active_phase). Marked as untrusted."

        # Now open fresh segment under new session
        check_single_active "$track_file"
        tmp=$(jq \
            --arg sid "$SESSION_ID" \
            --arg phase "$PHASE" \
            --arg transcript "$transcript" \
            --argjson bookmark "$current_line" \
            --arg started "$now" \
            '
            .active_session = $sid |
            .active_phase = $phase |
            .active_started = $started |
            .bookmark = $bookmark |
            if .sessions[$sid] then . else .sessions[$sid] = {transcript: $transcript, segments: []} end
            ' "$track_file")
        echo "$tmp" > "$track_file"
        echo "Started tracking $BEAD_ID phase=$PHASE session=$SESSION_ID at line $current_line"
        return
    fi

    # Different phase while current is active — error
    echo "Error: Bead '$BEAD_ID' is active in phase '$active_phase'. Run 'stop --bead $BEAD_ID' first."
    exit 1
}

# -----------------------------------------------------------------------------
# stop --bead
# -----------------------------------------------------------------------------
stop_bead() {
    local track_file="$TRACK_DIR/${BEAD_ID}.json"
    if [[ ! -f "$track_file" ]]; then
        echo "Error: No tracking data for '$BEAD_ID'."
        exit 1
    fi

    local active_phase active_session
    active_phase=$(jq_read '.active_phase // empty' "$track_file")
    active_session=$(jq_read '.active_session // empty' "$track_file")

    if [[ -z "$active_phase" || "$active_phase" == "null" ]]; then
        echo "Error: No active phase for '$BEAD_ID'. Already stopped."
        exit 1
    fi

    local transcript bookmark
    transcript=$(jq_read ".sessions[\"$active_session\"].transcript" "$track_file")
    bookmark=$(jq_read '.bookmark' "$track_file")
    local now
    now=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

    # Sum tokens from bookmark to current end
    local seg_tokens='{"input_tokens":0,"cache_read_tokens":0,"cache_create_tokens":0,"output_tokens":0,"turns":0}'
    if [[ -f "$transcript" ]]; then
        local current_line
        current_line=$(get_line_count "$transcript")
        if [[ "$bookmark" -lt "$current_line" ]]; then
            seg_tokens=$(sum_tokens "$transcript" "$((bookmark + 1))" "$current_line")
        fi
    fi

    # Bank segment and clear active state
    local tmp
    tmp=$(jq \
        --arg phase "$active_phase" \
        --arg sid "$active_session" \
        --arg stopped "$now" \
        --argjson seg "$seg_tokens" \
        '
        .sessions[$sid].segments += [{
            phase: $phase,
            started: (.active_started // "unknown"),
            stopped: $stopped,
            input_tokens: ((.sessions[$sid].banked_input // 0) + $seg.input_tokens),
            cache_read_tokens: ((.sessions[$sid].banked_cache_read // 0) + $seg.cache_read_tokens),
            cache_create_tokens: ((.sessions[$sid].banked_cache_create // 0) + $seg.cache_create_tokens),
            output_tokens: ((.sessions[$sid].banked_output // 0) + $seg.output_tokens),
            turns: ((.sessions[$sid].banked_turns // 0) + $seg.turns)
        }] |
        del(.sessions[$sid].banked_input, .sessions[$sid].banked_cache_read,
            .sessions[$sid].banked_cache_create, .sessions[$sid].banked_output,
            .sessions[$sid].banked_turns) |
        .active_phase = null |
        .active_session = null |
        .active_started = null |
        .bookmark = null
        ' "$track_file")
    echo "$tmp" > "$track_file"

    if $JSON_OUTPUT; then
        output_bead_json "$track_file"
    else
        echo "Stopped tracking $BEAD_ID phase=$active_phase"
    fi
}

# -----------------------------------------------------------------------------
# status --bead
# -----------------------------------------------------------------------------
status_bead() {
    local track_file="$TRACK_DIR/${BEAD_ID}.json"
    if [[ ! -f "$track_file" ]]; then
        echo "Error: No tracking data for '$BEAD_ID'."
        exit 1
    fi

    if $JSON_OUTPUT; then
        # If there's an active phase, include in-progress tokens in output
        local active_phase active_session
        active_phase=$(jq_read '.active_phase // empty' "$track_file")
        active_session=$(jq_read '.active_session // empty' "$track_file")

        if [[ -n "$active_phase" && "$active_phase" != "null" ]]; then
            local transcript bookmark
            transcript=$(jq_read ".sessions[\"$active_session\"].transcript" "$track_file")
            bookmark=$(jq_read '.bookmark' "$track_file")

            local in_progress='{"input_tokens":0,"cache_read_tokens":0,"cache_create_tokens":0,"output_tokens":0,"turns":0}'
            if [[ -f "$transcript" ]]; then
                local current_line
                current_line=$(get_line_count "$transcript")
                if [[ "$bookmark" -lt "$current_line" ]]; then
                    in_progress=$(sum_tokens "$transcript" "$((bookmark + 1))" "$current_line")
                fi
            fi

            jq \
                --arg phase "$active_phase" \
                --arg sid "$active_session" \
                --argjson prog "$in_progress" \
                '
                {
                    work_id: .work_id,
                    active_phase: .active_phase,
                    active_session: .active_session,
                    sessions: (.sessions | to_entries | map({
                        key: .key,
                        value: {
                            transcript: .value.transcript,
                            segments: .value.segments
                        }
                    }) | from_entries),
                    in_progress: {
                        session: $sid,
                        phase: $phase,
                        input_tokens: ((.sessions[$sid].banked_input // 0) + $prog.input_tokens),
                        cache_read_tokens: ((.sessions[$sid].banked_cache_read // 0) + $prog.cache_read_tokens),
                        cache_create_tokens: ((.sessions[$sid].banked_cache_create // 0) + $prog.cache_create_tokens),
                        output_tokens: ((.sessions[$sid].banked_output // 0) + $prog.output_tokens),
                        turns: ((.sessions[$sid].banked_turns // 0) + $prog.turns)
                    },
                    totals: (
                        [.sessions[].segments[]] +
                        [{
                            input_tokens: ((.sessions[$sid].banked_input // 0) + $prog.input_tokens),
                            cache_read_tokens: ((.sessions[$sid].banked_cache_read // 0) + $prog.cache_read_tokens),
                            cache_create_tokens: ((.sessions[$sid].banked_cache_create // 0) + $prog.cache_create_tokens),
                            output_tokens: ((.sessions[$sid].banked_output // 0) + $prog.output_tokens),
                            turns: ((.sessions[$sid].banked_turns // 0) + $prog.turns)
                        }]
                    ) | {
                        input_tokens: (map(.input_tokens) | add // 0),
                        cache_read_tokens: (map(.cache_read_tokens) | add // 0),
                        cache_create_tokens: (map(.cache_create_tokens) | add // 0),
                        output_tokens: (map(.output_tokens) | add // 0),
                        turns: (map(.turns) | add // 0)
                    }
                }
                ' "$track_file"
        else
            output_bead_json "$track_file"
        fi
    else
        local active_phase
        active_phase=$(jq_read '.active_phase // "none"' "$track_file")
        local seg_count
        seg_count=$(jq '[.sessions[].segments[]] | length' "$track_file")
        echo "=== $BEAD_ID ==="
        echo "  active_phase: $active_phase"
        echo "  segments: $seg_count"
    fi
}

# -----------------------------------------------------------------------------
# JSON output helper for --bead
# -----------------------------------------------------------------------------
output_bead_json() {
    local track_file="$1"
    jq '
    {
        work_id: .work_id,
        active_phase: .active_phase,
        active_session: .active_session,
        sessions: (.sessions | to_entries | map({
            key: .key,
            value: {
                transcript: .value.transcript,
                segments: .value.segments
            }
        }) | from_entries),
        totals: (
            [.sessions[].segments[]] | {
                input_tokens: (map(.input_tokens) | add // 0),
                cache_read_tokens: (map(.cache_read_tokens) | add // 0),
                cache_create_tokens: (map(.cache_create_tokens) | add // 0),
                output_tokens: (map(.output_tokens) | add // 0),
                turns: (map(.turns) | add // 0)
            }
        )
    }
    ' "$track_file"
}

# -----------------------------------------------------------------------------
# start --coordinate
# -----------------------------------------------------------------------------
start_coordinate() {
    [[ -z "$SESSION_ID" ]] && { echo "Error: --session is required for start."; exit 1; }

    local transcript
    transcript=$(resolve_transcript "$SESSION_ID")
    local track_file="$TRACK_DIR/coordinate.${SESSION_ID}.json"
    local now
    now=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
    local current_line
    current_line=$(get_line_count "$transcript")

    # Convert comma-separated beads to JSON array
    local beads_json
    beads_json=$(echo "$BEADS_LIST" | tr ',' '\n' | jq -R . | jq -s .)

    if [[ -f "$track_file" ]]; then
        local active
        active=$(jq_read '.active // empty' "$track_file")
        if [[ "$active" == "true" ]]; then
            echo "Error: Coordination already active for session $SESSION_ID. Run 'stop --coordinate --session $SESSION_ID' first."
            exit 1
        fi
        # Append new coordination to existing file
        check_single_active "$track_file"
        local tmp
        tmp=$(jq \
            --argjson beads "$beads_json" \
            --argjson bookmark "$current_line" \
            --arg started "$now" \
            '
            .active = true |
            .beads = $beads |
            .bookmark = $bookmark |
            .started = $started |
            .stopped = null
            ' "$track_file")
        echo "$tmp" > "$track_file"
    else
        check_single_active ""
        jq -n \
            --arg type "coordinate" \
            --arg sid "$SESSION_ID" \
            --argjson beads "$beads_json" \
            --arg transcript "$transcript" \
            --argjson bookmark "$current_line" \
            --arg started "$now" \
            '{
                type: $type,
                session_id: $sid,
                beads: $beads,
                transcript: $transcript,
                bookmark: $bookmark,
                active: true,
                started: $started,
                stopped: null,
                segments: []
            }' > "$track_file"
    fi

    echo "Started coordination tracking for $(echo "$BEADS_LIST" | tr ',' ' ') session=$SESSION_ID at line $current_line"
}

# -----------------------------------------------------------------------------
# stop --coordinate
# -----------------------------------------------------------------------------
stop_coordinate() {
    [[ -z "$SESSION_ID" ]] && { echo "Error: --session is required for stop --coordinate."; exit 1; }

    local track_file="$TRACK_DIR/coordinate.${SESSION_ID}.json"
    if [[ ! -f "$track_file" ]]; then
        echo "Error: No coordination tracking for session '$SESSION_ID'."
        exit 1
    fi

    local active
    active=$(jq_read '.active // empty' "$track_file")
    if [[ "$active" != "true" ]]; then
        echo "Error: No active coordination for session '$SESSION_ID'. Already stopped."
        exit 1
    fi

    local transcript bookmark
    transcript=$(jq_read '.transcript' "$track_file")
    bookmark=$(jq_read '.bookmark' "$track_file")
    local now
    now=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

    local seg_tokens='{"input_tokens":0,"cache_read_tokens":0,"cache_create_tokens":0,"output_tokens":0,"turns":0}'
    if [[ -f "$transcript" ]]; then
        local current_line
        current_line=$(get_line_count "$transcript")
        if [[ "$bookmark" -lt "$current_line" ]]; then
            seg_tokens=$(sum_tokens "$transcript" "$((bookmark + 1))" "$current_line")
        fi
    fi

    local tmp
    tmp=$(jq \
        --arg stopped "$now" \
        --argjson seg "$seg_tokens" \
        '
        .segments += [{
            phase: "coordinate",
            started: .started,
            stopped: $stopped,
            input_tokens: $seg.input_tokens,
            cache_read_tokens: $seg.cache_read_tokens,
            cache_create_tokens: $seg.cache_create_tokens,
            output_tokens: $seg.output_tokens,
            turns: $seg.turns
        }] |
        .active = false |
        .stopped = $stopped |
        .bookmark = null
        ' "$track_file")
    echo "$tmp" > "$track_file"

    if $JSON_OUTPUT; then
        jq '
        {
            type: .type,
            session_id: .session_id,
            beads: .beads,
            segments: .segments,
            totals: (.segments | {
                input_tokens: (map(.input_tokens) | add // 0),
                cache_read_tokens: (map(.cache_read_tokens) | add // 0),
                cache_create_tokens: (map(.cache_create_tokens) | add // 0),
                output_tokens: (map(.output_tokens) | add // 0),
                turns: (map(.turns) | add // 0)
            })
        }
        ' "$track_file"
    else
        echo "Stopped coordination tracking for session $SESSION_ID"
    fi
}

# -----------------------------------------------------------------------------
# status --coordinate
# -----------------------------------------------------------------------------
status_coordinate() {
    [[ -z "$SESSION_ID" ]] && { echo "Error: --session is required for status --coordinate."; exit 1; }

    local track_file="$TRACK_DIR/coordinate.${SESSION_ID}.json"
    if [[ ! -f "$track_file" ]]; then
        echo "Error: No coordination tracking for session '$SESSION_ID'."
        exit 1
    fi

    if $JSON_OUTPUT; then
        local active
        active=$(jq_read '.active // empty' "$track_file")
        if [[ "$active" == "true" ]]; then
            local transcript bookmark
            transcript=$(jq_read '.transcript' "$track_file")
            bookmark=$(jq_read '.bookmark' "$track_file")

            local in_progress='{"input_tokens":0,"cache_read_tokens":0,"cache_create_tokens":0,"output_tokens":0,"turns":0}'
            if [[ -f "$transcript" ]]; then
                local current_line
                current_line=$(get_line_count "$transcript")
                if [[ "$bookmark" -lt "$current_line" ]]; then
                    in_progress=$(sum_tokens "$transcript" "$((bookmark + 1))" "$current_line")
                fi
            fi

            jq \
                --argjson prog "$in_progress" \
                '
                {
                    type: .type,
                    session_id: .session_id,
                    beads: .beads,
                    active: .active,
                    segments: .segments,
                    in_progress: {
                        phase: "coordinate",
                        input_tokens: $prog.input_tokens,
                        cache_read_tokens: $prog.cache_read_tokens,
                        cache_create_tokens: $prog.cache_create_tokens,
                        output_tokens: $prog.output_tokens,
                        turns: $prog.turns
                    },
                    totals: (
                        [.segments[], $prog] | {
                            input_tokens: (map(.input_tokens) | add // 0),
                            cache_read_tokens: (map(.cache_read_tokens) | add // 0),
                            cache_create_tokens: (map(.cache_create_tokens) | add // 0),
                            output_tokens: (map(.output_tokens) | add // 0),
                            turns: (map(.turns) | add // 0)
                        }
                    )
                }
                ' "$track_file"
        else
            jq '
            {
                type: .type,
                session_id: .session_id,
                beads: .beads,
                active: .active,
                segments: .segments,
                totals: (.segments | {
                    input_tokens: (map(.input_tokens) | add // 0),
                    cache_read_tokens: (map(.cache_read_tokens) | add // 0),
                    cache_create_tokens: (map(.cache_create_tokens) | add // 0),
                    output_tokens: (map(.output_tokens) | add // 0),
                    turns: (map(.turns) | add // 0)
                })
            }
            ' "$track_file"
        fi
    else
        local active
        active=$(jq_read '.active // "false"' "$track_file")
        echo "=== Coordinate: $SESSION_ID ==="
        echo "  active: $active"
        echo "  beads: $(jq_read '.beads | join(", ")' "$track_file")"
    fi
}

# -----------------------------------------------------------------------------
# list
# -----------------------------------------------------------------------------
do_list() {
    echo "=== Token Tracking ==="
    local found=0

    # New JSON track files
    for f in "$TRACK_DIR"/*.json; do
        [[ -f "$f" ]] || continue
        local name
        name=$(basename "$f" .json)
        local ap
        ap=$(jq_read '.active_phase // .active // "false"' "$f")
        local seg_count
        seg_count=$(jq '[.sessions[].segments[] // .segments[]] | length' "$f" 2>/dev/null || echo "0")
        if [[ "$ap" != "null" && "$ap" != "false" && -n "$ap" ]]; then
            echo "  $name (active: phase=$ap, segments=$seg_count)"
        else
            echo "  $name (stopped, segments=$seg_count)"
        fi
        found=1
    done

    # Legacy shell-sourceable files (backward compat)
    for f in "$TRACK_DIR"/*; do
        [[ -f "$f" ]] || continue
        case "$f" in *.json) continue ;; esac
        local name
        name=$(basename "$f")
        case "$name" in
            *.done)
                name="${name%.done}"
                echo "  $name (legacy, completed)"
                ;;
            *)
                echo "  $name (legacy, in progress)"
                ;;
        esac
        found=1
    done

    [[ "$found" -eq 0 ]] && echo "  (none)" || true
}

# -----------------------------------------------------------------------------
# Command dispatch
# -----------------------------------------------------------------------------
case "$ACTION" in
    start)
        if $COORDINATE; then
            validate_mode
            start_coordinate
        elif [[ -n "$BEAD_ID" ]]; then
            validate_mode
            start_bead
        else
            echo "Error: Specify --bead <id> or --coordinate --beads <id1,id2,...>."
            exit 1
        fi
        ;;
    stop)
        if $COORDINATE; then
            stop_coordinate
        elif [[ -n "$BEAD_ID" ]]; then
            stop_bead
        else
            echo "Error: Specify --bead <id> or --coordinate --session <id>."
            exit 1
        fi
        ;;
    status)
        if $COORDINATE; then
            status_coordinate
        elif [[ -n "$BEAD_ID" ]]; then
            status_bead
        else
            echo "Error: Specify --bead <id> or --coordinate --session <id>."
            exit 1
        fi
        ;;
    list)
        do_list
        ;;
    *)
        cat << 'HELP'
token-tracking.sh — Phase-aware token tracking per work item

Commands:
  start   --bead <id> --phase <phase> --session <sid>   Track individual bead
  start   --coordinate --beads <ids> --session <sid>     Track batch coordination
  stop    --bead <id> [--json]                           Finalize active phase
  stop    --coordinate --session <sid> [--json]          Finalize coordination
  status  --bead <id> [--json]                           Check running totals
  status  --coordinate --session <sid> [--json]          Check coordination totals
  list                                                   Show all tracked items

Modes:
  --bead <id>        Individual bead work (requires --phase on start)
  --coordinate       Batch planning (requires --beads on start)

Phases (--bead only):
  plan, discover, implement, test, fix

Rules:
  - Only one tracking active at a time
  - Phase transitions: explicit stop + start
  - Resume: start same bead + same phase + same session
  - --coordinate and --bead are mutually exclusive

Storage:
  Per-bead:       ~/.claude/.token_tracking/<bead-id>.json
  Coordinate:     ~/.claude/.token_tracking/coordinate.<session-id>.json
HELP
        exit 1
        ;;
esac
