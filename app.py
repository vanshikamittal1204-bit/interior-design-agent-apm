import streamlit as st

from planner import Planner, PlannerRequest
from tools.evaluation_agent import EvaluationItem, EvaluationRejectedItem, EvaluationRequest, evaluate_plan

ROOM_TYPE_OPTIONS = ["living room", "bedroom", "study", "dining room"]
STYLE_OPTIONS = ["modern", "contemporary", "minimalist", "bohemian", "industrial", "traditional", "scandinavian"]
STYLE_ALIAS_MAP = {"modern": "Contemporary"}


def _parse_must_haves(raw_value: str) -> list[str]:
    if not raw_value:
        return []
    return [entry.strip() for entry in raw_value.split(",") if entry.strip()]


def _to_evaluation_item(item):
    return EvaluationItem(
        item_id=item.item_id,
        category=item.category,
        name=item.name,
        price_inr=item.price_inr,
    )


def _to_evaluation_rejected_item(rejected):
    return EvaluationRejectedItem(item_name=rejected.item_name, reason=rejected.reason)


def _build_evaluation_request(planner_request: PlannerRequest, planner_result):
    return EvaluationRequest(
        selected_items=[_to_evaluation_item(item) for item in planner_result.selected_items],
        optional_additions=[_to_evaluation_item(item) for item in planner_result.optional_additions],
        rejected_items=[_to_evaluation_rejected_item(item) for item in planner_result.rejected_items],
        layout_plan=planner_result.layout_plan,
        room_type=planner_request.room_type,
        room_width_cm=planner_request.room_width_cm,
        room_depth_cm=planner_request.room_depth_cm,
        budget_inr=planner_request.budget,
        style_preference=planner_request.style,
        must_haves=planner_request.must_haves,
        notes=planner_request.notes,
    )


def _summarize_items(items):
    return [
        {
            "Item ID": item.item_id,
            "Category": item.category,
            "Name": item.name,
            "Price (INR)": item.price_inr,
        }
        for item in items
    ]


def _summarize_rejected_items(items):
    return [
        {
            "Item Name": item.item_name,
            "Reason": item.reason,
        }
        for item in items
    ]


def main() -> None:
    st.title("Interior Design Agent")
    st.write("Use the form below to generate a room design plan and evaluate the results.")

    with st.form(key="planner_form"):
        room_type = st.selectbox("Room Type", ROOM_TYPE_OPTIONS)
        style = st.selectbox("Style", STYLE_OPTIONS)
        budget = st.number_input("Budget (INR)", min_value=1000, value=40000, step=500)
        room_width = st.number_input("Room Width (cm)", min_value=100, value=400, step=10)
        room_depth = st.number_input("Room Depth (cm)", min_value=100, value=350, step=10)
        must_haves_raw = st.text_input("Must-Have Items", help="Enter comma-separated items or categories.")
        notes = st.text_area("Notes / Preferences", help="Add any design notes, like 'cozy' or 'movie night'.")
        generate = st.form_submit_button("Generate Plan")

    if not generate:
        return

    must_haves = _parse_must_haves(must_haves_raw)
    normalized_style = STYLE_ALIAS_MAP.get(style.lower(), style)

    try:
        planner_request = PlannerRequest(
            room_type=room_type,
            style=normalized_style,
            budget=budget,
            room_width_cm=room_width,
            room_depth_cm=room_depth,
            must_haves=must_haves,
            notes=notes,
        )
    except ValueError as error:
        st.error(f"Invalid input: {error}")
        return

    planner = Planner()

    with st.spinner("Generating design plan..."):
        planner_result = planner.generate_plan(planner_request)

    evaluation_request = _build_evaluation_request(planner_request, planner_result)
    evaluation_result = evaluate_plan(evaluation_request)
    st.header("Planner Results")

    # 7. Layout Plan
    st.subheader("Layout Plan")
    layout = planner_result.layout_plan
    if layout and layout.best_layout and layout.best_layout.placements:
        st.write("Coordinate placements are available for the chosen layout. (Tabular view)")
        placements = [
            {
                "Item ID": p.item_id,
                "Name": p.item_name,
                "Category": p.category,
                "X (cm)": p.x,
                "Y (cm)": p.y,
                "Width (cm)": p.width,
                "Depth (cm)": p.depth,
            }
            for p in layout.best_layout.placements
        ]
        st.table(placements or [{"Message": "No placement data."}])
        if layout.best_layout.pros:
            st.write("**Layout Pros:**")
            for p in layout.best_layout.pros:
                st.write(f"- {p}")
        if layout.best_layout.cons:
            st.write("**Layout Cons:**")
            for c in layout.best_layout.cons:
                st.write(f"- {c}")
    else:
        # textual summary using existing planner/layout outputs only
        st.write("Coordinate layout is Not Available. Showing layout summary:")
        if layout and layout.failure_reasons:
            for r in layout.failure_reasons:
                st.write(f"- {r}")
        else:
            st.write("- No detailed layout was produced.")

    # 11. Selected Furniture
    st.subheader("Selected Furniture (Mandatory)")
    st.table(_summarize_items(planner_result.selected_items) or [{"Message": "No selected items."}])

    # 12. Optional Additions
    st.subheader("Optional Additions")
    st.table(_summarize_items(planner_result.optional_additions) or [{"Message": "No optional additions."}])

    # BOQ Summary
    st.subheader("BOQ Summary")
    mandatory_cost = sum(getattr(i, "price_inr", 0) for i in planner_result.selected_items)
    optional_cost = sum(getattr(i, "price_inr", 0) for i in planner_result.optional_additions)
    total_proposed = mandatory_cost + optional_cost
    budget_value = planner_request.budget
    remaining_budget = budget_value - total_proposed
    utilization_pct = round((total_proposed / budget_value) * 100, 2) if budget_value else "Not Available"
    budget_status = "Within Budget" if total_proposed <= budget_value else "Over Budget"

    boq_cols = st.columns(2)
    boq_cols[0].metric("Mandatory Items Cost", f"INR {mandatory_cost}")
    boq_cols[1].metric("Optional Additions Cost", f"INR {optional_cost}")
    st.write(f"- Total Proposed Cost: INR {total_proposed}")
    st.write(f"- Budget: INR {budget_value}")
    st.write(f"- Remaining Budget: INR {remaining_budget}")
    st.write(f"- Budget Utilization %: {utilization_pct}")
    st.write(f"- Budget Status: {budget_status}")

    # Design Rationale
    st.subheader("Design Rationale")
    st.write("**Why These Items Were Selected**")
    if planner_result.selection_reasons:
        for r in planner_result.selection_reasons:
            st.write(f"- {r}")
    else:
        st.write("- Not Available")

    st.write("**Budget Rationale**")
    # Use planner outputs only (metrics and selection reasons)
    try:
        st.write(f"- Total cost of mandatory items: INR {mandatory_cost}")
        st.write(f"- Remaining budget after selections: INR {planner_result.remaining_budget}")
    except Exception:
        st.write("- Not Available")

    st.write("**Style Rationale**")
    if planner_request.style:
        st.write(f"- Style preference provided: {planner_request.style}")
        if planner_result.selection_reasons:
            st.write("- Selection notes:")
            for r in planner_result.selection_reasons[:4]:
                st.write(f"  - {r}")
    else:
        st.write("- Not Available")

    # Rejected items
    st.subheader("Rejected Items")
    st.table(_summarize_rejected_items(planner_result.rejected_items) or [{"Message": "No rejected items."}])

    # Evaluation - moved to end
    st.header("Evaluation")
    eval_cols = st.columns(2)
    eval_cols[0].metric("Overall Score", f"{evaluation_result.overall_score}/100")
    eval_cols[1].metric("Confidence Level", f"{evaluation_result.confidence_level}/100")

    st.subheader("Score Breakdown")
    st.table(
        [{"Criteria": key.replace("_", " ").title(), "Score": value} for key, value in evaluation_result.score_breakdown.items()]
    )

    st.subheader("Pros")
    for item in evaluation_result.pros:
        st.write(f"- {item}")

    st.subheader("Cons")
    for item in evaluation_result.cons:
        st.write(f"- {item}")

    st.subheader("Reasoning")
    for item in evaluation_result.reasoning:
        st.write(f"- {item}")

    st.subheader("Transparency Metrics")
    # Display available metrics only; if unavailable show Not Available
    def _safe_get(dct, key):
        try:
            return dct.get(key)
        except Exception:
            return None

    catalog_compliance = evaluation_result.score_breakdown.get("must_have_coverage") if getattr(evaluation_result, "score_breakdown", None) else None
    budget_compliance = evaluation_result.score_breakdown.get("budget_utilization") if getattr(evaluation_result, "score_breakdown", None) else None
    layout_status = "Passed" if getattr(planner_result, "layout_passed", None) else ("Failed" if getattr(planner_result, "layout_passed", None) is not None else "Not Available")
    replan_count = getattr(planner_result, "replan_count", "Not Available")
    # Out-of-scope, catalog violations, invented items likely not produced by current pipeline
    out_of_scope = sum(1 for r in planner_result.rejected_items if "out of scope" in (r.reason or "").lower()) if planner_result.rejected_items is not None else "Not Available"
    catalog_violations = "Not Available"
    invented_items = "Not Available"

    tm_cols = st.columns(2)
    tm_cols[0].write(f"- Catalog Compliance: {catalog_compliance if catalog_compliance is not None else 'Not Available'}")
    tm_cols[1].write(f"- Budget Compliance: {budget_compliance if budget_compliance is not None else 'Not Available'}")
    tm_cols[0].write(f"- Layout Validation Status: {layout_status}")
    tm_cols[1].write(f"- Replan Count: {replan_count}")
    tm_cols[0].write(f"- Out-of-Scope Requests: {out_of_scope if out_of_scope != 0 else 0}")
    tm_cols[1].write(f"- Catalog Violations: {catalog_violations}")
    tm_cols[0].write(f"- Invented Items: {invented_items}")


if __name__ == "__main__":
    main()
