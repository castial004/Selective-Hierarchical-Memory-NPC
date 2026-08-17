def generate_explanation(selected_action,evidence,max_reasons=2):
    causal=[e for e in evidence if e.changed_action or abs(e.score_delta)>=.12][:max_reasons]
    if not causal: return f"The NPC selected '{selected_action}' mainly from the current game state."
    reasons='; '.join(e.factor_name for e in causal)
    return f"The NPC selected '{selected_action}' because these factors materially affected the decision: {reasons}."
