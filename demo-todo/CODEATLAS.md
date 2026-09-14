---
project: demo-todo
generated: 2026-09-14 14:30
language: zh
files: 8
symbols: 24
last_scan: 2026-09-14T06:30:24+00:00
---

> 首次使用请运行 `codeatlas scan .` 生成完整明细（.codeatlas/detail/）。

## 架构图 / Diagrams

### 目录结构 / Directory Tree

```mermaid
graph TD
    d___root___f1fabfb4["/"]
    d_app_d2a57dc1["app"]
    d___root___f1fabfb4 --> d_app_d2a57dc1
    d_app_controllers_ec393090["controllers"]
    d_app_d2a57dc1 --> d_app_controllers_ec393090
    f_s_task_controller_py_01adda22["task_controller.py"]
    d_app_controllers_ec393090 --> f_s_task_controller_py_01adda22
    f_app_main_py_4dd44bb1["main.py"]
    d_app_d2a57dc1 --> f_app_main_py_4dd44bb1
    d_app_models_83f1a1cd["models"]
    d_app_d2a57dc1 --> d_app_models_83f1a1cd
    f_app_models_task_py_28558009["task.py"]
    d_app_models_83f1a1cd --> f_app_models_task_py_28558009
    f_app_models_user_py_9ee06fb9["user.py"]
    d_app_models_83f1a1cd --> f_app_models_user_py_9ee06fb9
    d_app_services_f0f81ece["services"]
    d_app_d2a57dc1 --> d_app_services_f0f81ece
    f_ices_auth_service_py_52e4f9b9["auth_service.py"]
    d_app_services_f0f81ece --> f_ices_auth_service_py_52e4f9b9
    f_ices_task_service_py_e6f54bf9["task_service.py"]
    d_app_services_f0f81ece --> f_ices_task_service_py_e6f54bf9
    d_app_utils_b1a370ad["utils"]
    d_app_d2a57dc1 --> d_app_utils_b1a370ad
    f__utils_validators_py_1e60377a["validators.py"]
    d_app_utils_b1a370ad --> f__utils_validators_py_1e60377a
    d_static_a81259ce["static"]
    d___root___f1fabfb4 --> d_static_a81259ce
    f_static_task_panel_ts_6dc6b217["task_panel.ts"]
    d_static_a81259ce --> f_static_task_panel_ts_6dc6b217
```

### 模块依赖 / Module Dependencies

```mermaid
flowchart LR
    m_s_task_controller_py_01adda22["task_controller.py"]
    m_ices_task_service_py_e6f54bf9["task_service.py"]
    m_s_task_controller_py_01adda22 -->|"1"| m_ices_task_service_py_e6f54bf9
    m_app_main_py_4dd44bb1["main.py"]
    m_app_main_py_4dd44bb1 -->|"1"| m_s_task_controller_py_01adda22
    m_ices_auth_service_py_52e4f9b9["auth_service.py"]
    m_app_models_user_py_9ee06fb9["user.py"]
    m_ices_auth_service_py_52e4f9b9 -->|"1"| m_app_models_user_py_9ee06fb9
    m_app_models_task_py_28558009["task.py"]
    m_ices_task_service_py_e6f54bf9 -->|"1"| m_app_models_task_py_28558009
```

### 类继承 / Class Inheritance

```mermaid
classDiagram
    class c_oller_TaskController_dcf4cab4 {
        TaskController
    }
    class c_app_models_task_Task_feedb407 {
        Task
    }
    class c_app_models_user_User_5d893c70 {
        User
    }
    class c__service_AuthService_c634763f {
        AuthService
    }
    class c__service_TaskService_7da624af {
        TaskService
    }
    class c_task_panel_TaskPanel_7391d676 {
        TaskPanel
    }
```

## 文件索引 / Files

| 文件 | 语言 | 角色 | 符号数 | 被引用 |
|---|---|---|---:|---:|
| `app/controllers/task_controller.py` | python | controller | 4 | 1 |
| `app/main.py` | python | entry | 1 | 0 |
| `app/models/task.py` | python | model | 3 | 1 |
| `app/models/user.py` | python | model | 2 | 1 |
| `app/services/auth_service.py` | python | service | 3 | 0 |
| `app/services/task_service.py` | python | service | 6 | 1 |
| `app/utils/validators.py` | python | util | 1 | 0 |
| `static/task_panel.ts` | typescript | module | 4 | 0 |
