"""Native gateway entry with a small Vision-only live prompt adapter."""
from tui_gateway import server
import json


@server.method('vision.conversation.persist')
def persist_conversation(rid, params):
    session, error = server._sess_nowait(params, rid)
    if error:
        return error
    try:
        with session['history_lock']:
            server._ensure_session_db_row(session)
            key = session.get('session_key')
            with server._session_db(session) as db:
                if db is None or not key or not db.get_session(key):
                    return server._err(rid, 5006, 'The conversation could not be saved in the native session store.')
        return server._ok(rid, {'stored_session_id': key})
    except Exception as exc:
        return server._err(rid, 5006, str(exc))


@server.method('vision.profiles')
def profiles(rid, params):
    try:
        from hermes_cli.profiles import list_profiles, create_profile
        if params.get('action') == 'create':
            from hermes_constants import get_hermes_home
            home = get_hermes_home()
            source = home.name if home.parent.name == 'profiles' else 'default'
            create_profile(params.get('name', ''), clone_from=source if params.get('inherit', True) else None,
                           clone_config=bool(params.get('inherit', True)), no_alias=True,
                           description=params.get('description', ''))
        return server._ok(rid, {'profiles': [
            {'name': item.name, 'description': item.description, 'model': item.model,
             'provider': item.provider, 'skills': item.skill_count}
            for item in list_profiles()]})
    except Exception as exc:
        return server._err(rid, 4002, str(exc))


@server.method('vision.schedules')
def schedules(rid, params):
    try:
        from tools.cronjob_tools import cronjob
        action = params.get('action', 'list')
        if action not in {'list', 'create', 'update', 'pause', 'resume', 'remove', 'run'}:
            return server._err(rid, 4002, 'Unsupported schedule action')
        allowed = {'job_id', 'name', 'prompt', 'schedule', 'repeat', 'deliver'}
        args = {key: value for key, value in params.items() if key in allowed}
        result = json.loads(cronjob(action=action, include_disabled=True, **args))
        if action == 'list':
            from cron.jobs import get_job
            for job in result.get('jobs', []):
                job['id'] = job['job_id']
                raw = get_job(job['job_id']) or {}
                job['prompt'] = raw.get('prompt', '')
                job['schedule_input'] = (raw.get('schedule') or {}).get('display') or job.get('schedule', '')
        if result.get('success') is False or result.get('error'):
            return server._err(rid, 4002, str(result.get('error') or result.get('message')))
        return server._ok(rid, result)
    except Exception as exc:
        return server._err(rid, 4002, str(exc))


@server.method('vision.schedule.tick')
def schedule_tick(rid, params):
    from cron.scheduler import tick
    return server._ok(rid, {'dispatched': tick(verbose=False, sync=False)})


@server.method('vision.learning')
def learning(rid, params):
    from agent.learning_graph import build_learning_graph
    return server._ok(rid, build_learning_graph())


@server.method('vision.prompt.reload')
def reload_prompt(rid, params):
    session, error = server._sess_nowait(params, rid)
    if error:
        return error
    with session['history_lock']:
        if session.get('running'):
            return server._err(rid, 4009, 'Finish the current task before changing instructions')
        prompt = server._prompt_text((server._load_cfg().get('agent') or {}).get('system_prompt', ''))
        agent = session.get('agent')
        if agent is not None:
            agent.ephemeral_system_prompt = prompt or None
            agent._cached_system_prompt = None
    return server._ok(rid, {'applied': True})


@server.method('vision.memory.reload')
def reload_memory(rid, params):
    session, error = server._sess_nowait(params, rid)
    if error:
        return error
    with session['history_lock']:
        if session.get('running'):
            return server._err(rid, 4009, 'Finish the current task before reloading memory')
        agent = session.get('agent')
        if agent is not None:
            store = getattr(agent, '_memory_store', None)
            if store is not None:
                store.load_from_disk()
            agent._cached_system_prompt = None
    return server._ok(rid, {'applied': True})


from backend.native_app_tool import install as install_application_tool
install_application_tool(server)


if __name__ == '__main__':
    from tui_gateway.entry import main
    main()
