<script lang="ts">
  import { onMount } from "svelte";
  import { Plus, X } from "lucide-svelte";

  interface Panel {
    id: string;
    component: any;
    props?: any;
    x: number;
    y: number;
    width: number;
    height: number;
  }

  interface Props {
    panels: Panel[];
    cols?: number;
    rows?: number;
    onAddPanel?: () => void;
  }

  let {
    panels = $bindable([]),
    cols = 12,
    rows = 12,
    onAddPanel,
  }: Props = $props();

  let draggingPanel: string | null = $state(null);
  let resizingPanel: string | null = $state(null);
  let resizeDirection: string | null = $state(null);
  let startX = $state(0);
  let startY = $state(0);
  let startWidth = $state(0);
  let startHeight = $state(0);
  let startPanelX = $state(0);
  let startPanelY = $state(0);

  const cellSize = 100 / cols;

  function snapToGrid(value: number): number {
    return Math.round(value / cellSize) * cellSize;
  }

  function handleMouseDown(
    e: MouseEvent,
    panelId: string,
    isDrag: boolean = true,
  ) {
    if (isDrag) {
      draggingPanel = panelId;
      const panel = panels.find((p) => p.id === panelId);
      if (panel) {
        startX = e.clientX;
        startY = e.clientY;
        startPanelX = panel.x;
        startPanelY = panel.y;
      }
    }
    e.preventDefault();
  }

  function handleResizeMouseDown(
    e: MouseEvent,
    panelId: string,
    direction: string,
  ) {
    resizingPanel = panelId;
    resizeDirection = direction;
    const panel = panels.find((p) => p.id === panelId);
    if (panel) {
      startX = e.clientX;
      startY = e.clientY;
      startWidth = panel.width;
      startHeight = panel.height;
      startPanelX = panel.x;
      startPanelY = panel.y;
    }
    e.preventDefault();
    e.stopPropagation();
  }

  function handleMouseMove(e: MouseEvent) {
    if (draggingPanel) {
      const panel = panels.find((p) => p.id === draggingPanel);
      if (panel) {
        const containerWidth = window.innerWidth;
        const containerHeight = window.innerHeight;

        const deltaX = ((e.clientX - startX) / containerWidth) * 100;
        const deltaY = ((e.clientY - startY) / containerHeight) * 100;

        panel.x = Math.max(
          0,
          Math.min(100 - panel.width, snapToGrid(startPanelX + deltaX)),
        );
        panel.y = Math.max(
          0,
          Math.min(100 - panel.height, snapToGrid(startPanelY + deltaY)),
        );
      }
    } else if (resizingPanel && resizeDirection) {
      const panel = panels.find((p) => p.id === resizingPanel);
      if (panel) {
        const containerWidth = window.innerWidth;
        const containerHeight = window.innerHeight;

        const deltaX = ((e.clientX - startX) / containerWidth) * 100;
        const deltaY = ((e.clientY - startY) / containerHeight) * 100;

        if (resizeDirection.includes("e")) {
          panel.width = Math.max(
            cellSize,
            Math.min(100 - panel.x, snapToGrid(startWidth + deltaX)),
          );
        }
        if (resizeDirection.includes("w")) {
          const newX = snapToGrid(startPanelX + deltaX);
          const newWidth = snapToGrid(startWidth - deltaX);
          if (newWidth >= cellSize && newX >= 0) {
            panel.x = newX;
            panel.width = newWidth;
          }
        }
        if (resizeDirection.includes("s")) {
          panel.height = Math.max(
            cellSize,
            Math.min(100 - panel.y, snapToGrid(startHeight + deltaY)),
          );
        }
        if (resizeDirection.includes("n")) {
          const newY = snapToGrid(startPanelY + deltaY);
          const newHeight = snapToGrid(startHeight - deltaY);
          if (newHeight >= cellSize && newY >= 0) {
            panel.y = newY;
            panel.height = newHeight;
          }
        }
      }
    }
  }

  function handleMouseUp() {
    draggingPanel = null;
    resizingPanel = null;
    resizeDirection = null;
  }

  function removePanel(panelId: string) {
    panels = panels.filter((p) => p.id !== panelId);
  }

  onMount(() => {
    window.addEventListener("mousemove", handleMouseMove);
    window.addEventListener("mouseup", handleMouseUp);

    return () => {
      window.removeEventListener("mousemove", handleMouseMove);
      window.removeEventListener("mouseup", handleMouseUp);
    };
  });
</script>

<div class="relative w-full flex-1 overflow-hidden bg-black">
  <!-- Add Panel Button -->
  {#if onAddPanel}
    <button
      onclick={onAddPanel}
      class="fixed top-2 right-4 z-50 bg-transparent text-white rounded-full px-4 py-2
      hover:bg-stone-800 flex flex-row items-center gap-x-2 border border-stone-800"
      title="Add Panel"
    >
      <Plus size={18} /> Add a Panel
    </button>
  {/if}

  {#each panels as panel (panel.id)}
    <div
      class="absolute border border-stone-800 bg-black overflow-auto"
      style="left: {panel.x}%; top: {panel.y}%; width: {panel.width}%; height: {panel.height}%;"
    >
      <!-- Drag handle -->
      <div
        class="h-8 bg-stone-900 border-b border-stone-800 cursor-move flex items-center justify-between px-4"
        onmousedown={(e) => handleMouseDown(e, panel.id)}
      >
        <span class="text-sm font-medium text-stone-400">Panel</span>
        <button
          onclick={(e) => {
            e.stopPropagation();
            removePanel(panel.id);
          }}
          class="text-stone-400 hover:text-white hover:bg-stone-800 rounded p-1"
          title="Close Panel"
        >
          <X size={16} />
        </button>
      </div>

      <!-- Panel content -->
      <div class="p-4 h-[calc(100%-2rem)] overflow-auto">
        <svelte:component this={panel.component} {...panel.props || {}} />
      </div>

      <!-- Resize handles -->
      <div
        class="absolute top-0 right-0 w-2 h-full cursor-ew-resize hover:bg-blue-500/20"
        onmousedown={(e) => handleResizeMouseDown(e, panel.id, "e")}
      ></div>
      <div
        class="absolute bottom-0 left-0 h-2 w-full cursor-ns-resize hover:bg-blue-500/20"
        onmousedown={(e) => handleResizeMouseDown(e, panel.id, "s")}
      ></div>
      <div
        class="absolute top-0 left-0 w-2 h-full cursor-ew-resize hover:bg-blue-500/20"
        onmousedown={(e) => handleResizeMouseDown(e, panel.id, "w")}
      ></div>
      <div
        class="absolute top-0 left-0 h-2 w-full cursor-ns-resize hover:bg-blue-500/20"
        onmousedown={(e) => handleResizeMouseDown(e, panel.id, "n")}
      ></div>

      <!-- Corner resize handles -->
      <div
        class="absolute bottom-0 right-0 w-4 h-4 cursor-nwse-resize hover:bg-blue-500/40"
        onmousedown={(e) => handleResizeMouseDown(e, panel.id, "se")}
      ></div>
      <div
        class="absolute bottom-0 left-0 w-4 h-4 cursor-nesw-resize hover:bg-blue-500/40"
        onmousedown={(e) => handleResizeMouseDown(e, panel.id, "sw")}
      ></div>
      <div
        class="absolute top-0 right-0 w-4 h-4 cursor-nesw-resize hover:bg-blue-500/40"
        onmousedown={(e) => handleResizeMouseDown(e, panel.id, "ne")}
      ></div>
      <div
        class="absolute top-0 left-0 w-4 h-4 cursor-nwse-resize hover:bg-blue-500/40"
        onmousedown={(e) => handleResizeMouseDown(e, panel.id, "nw")}
      ></div>
    </div>
  {/each}
</div>
