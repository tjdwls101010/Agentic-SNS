"""Account protection shared by every invocation: one cross-process lock, a persisted block for what a person must
clear, per-operation limits from X's headers, pacing, a per-command budget and deadline. (Written in its slice.)"""
