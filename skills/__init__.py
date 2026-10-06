"""Vagar live skills.

Approved skill modules live in this directory. Each defines @function_tool
decorated async functions; they are imported fresh at every session start by
skill_manager.load_skill_tools().

Generated skills awaiting approval live in staging/ and are NEVER imported.
"""
