"""Interview mode (EPIC-10, ADR-0016): mock interviews over questions from
the user's own prep base (`~/www/self/cv/prep`), with a Claude review
afterwards through `claude_gateway`. Nothing here is imported by the
conversation path unless a character has `session_mode: interview`.
"""
