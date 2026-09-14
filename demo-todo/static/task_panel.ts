/**
 * 任务卡片组件。
 */

/**
 * 渲染单个任务卡片。
 */
export function renderTask(task: { id: number; title: string; done: boolean }): string {
    const status = task.done ? "done" : "pending";
    return `<div class="task ${status}">${task.title}</div>`;
}

/**
 * 任务面板：管理一批任务卡片的显示。
 */
export class TaskPanel {
    private items: { id: number; title: string; done: boolean }[] = [];

    /** 添加一个任务到面板。 */
    add(title: string): number {
        const id = this.items.length + 1;
        this.items.push({ id, title, done: false });
        return id;
    }

    /** 渲染整块面板 HTML。 */
    renderAll(): string {
        return this.items.map(renderTask).join("\n");
    }
}
