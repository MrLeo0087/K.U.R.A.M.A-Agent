"""Evaluations: the owner's real requests (from KURAMA's traces) replayed against the coding agent.

    routing.py   0 tokens, runs in the test suite: each real sentence must reach the right action
                 (tests/test_coder_evals.py)
    live.py      costs tokens, run by hand after a big change: real tasks on small sample projects, each with a
                 check of the result AND a token limit:  python -m coder.evals.live
"""
