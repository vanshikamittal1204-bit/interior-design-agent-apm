import streamlit as st

from planner import Planner, PlannerRequest
from tools.evaluation_agent import EvaluationItem, EvaluationRejectedItem, EvaluationRequest, evaluate_plan

ROOM_TYPE_OPTIONS = ["living room", "bedroom", "study", "dining room"]
STYLE_OPTIONS = ["modern", "contemporary", "minimalist", "bohemian", "industrial", "traditional", "scandinavian"]


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

    try:
        planner_request = PlannerRequest(
            room_type=room_type,
            style=style,
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

    st.subheader("Summary")
    columns = st.columns(4)
    columns[0].metric("Total Cost", f"INR {planner_result.total_cost}")
    columns[1].metric("Remaining Budget", f"INR {planner_result.remaining_budget}")
    columns[2].metric("Layout Status", "Passed" if planner_result.layout_passed else "Failed")
    columns[3].metric("Replan Count", planner_result.replan_count)

    st.subheader("Selected Items")
    st.table(_summarize_items(planner_result.selected_items) or [{"Message": "No selected items."}])

    st.subheader("Optional Additions")
    st.table(_summarize_items(planner_result.optional_additions) or [{"Message": "No optional additions."}])

    st.subheader("Rejected Items")
    st.table(_summarize_rejected_items(planner_result.rejected_items) or [{"Message": "No rejected items."}])

    st.subheader("Evaluation Results")
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


if __name__ == "__main__":
    main()
