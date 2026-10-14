"""Tests for TaskManager in modules/tasks.py."""

from __future__ import annotations

from modules.tasks import TaskManager


def test_task_add_and_list(tmp_db_path: str):
    manager = TaskManager(db_path=tmp_db_path)
    task1 = manager.add("Fix bug", "Investigate Groq timeout", priority="high")
    task2 = manager.add("Write tests", "Add pytest suite", priority="urgent")

    assert task1.id == 1
    assert task1.priority == "high"
    assert task2.priority == "urgent"

    tasks = manager.list_tasks()
    assert len(tasks) == 2
    # Urgent should be first
    assert tasks[0].priority == "urgent"


def test_task_status_lifecycle(tmp_db_path: str):
    manager = TaskManager(db_path=tmp_db_path)
    task = manager.add("Deploy bot", priority="medium")
    assert task.status == "pending"
    assert manager.pending_count() == 1

    in_prog = manager.set_status(task.id, "in_progress")
    assert in_prog is not None
    assert in_prog.status == "in_progress"

    done = manager.mark_done(task.id)
    assert done is not None
    assert done.status == "done"
    assert done.completed_at is not None
    assert manager.pending_count() == 0


def test_task_set_priority_and_delete(tmp_db_path: str):
    manager = TaskManager(db_path=tmp_db_path)
    task = manager.add("Review PR", priority="low")

    updated = manager.set_priority(task.id, "urgent")
    assert updated is not None
    assert updated.priority == "urgent"

    assert manager.delete(task.id) is True
    assert manager.get(task.id) is None


def test_task_handle_command(tmp_db_path: str):
    manager = TaskManager(db_path=tmp_db_path)

    # Help
    help_res = manager.handle_command("/task")
    assert help_res is not None
    assert "Smart Tasks" in help_res

    # Add
    add_res = manager.handle_command("/task add Clean database | Vacuum sqlite | high")
    assert add_res is not None
    assert "টাস্ক যোগ হয়েছে" in add_res

    # List
    list_res = manager.handle_command("/task list")
    assert list_res is not None
    assert "Clean database" in list_res

    # Done
    done_res = manager.handle_command("/task done 1")
    assert done_res is not None
    assert "সম্পন্ন" in done_res
