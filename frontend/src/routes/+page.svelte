<script lang="ts">
  import GridLayout from "$lib/nav/GridLayout.svelte";
  import PanelNavigator from "$lib/windows/PanelNavigator.svelte";

  let panels = $state([
    {
      id: crypto.randomUUID(),
      component: PanelNavigator,
      x: 0,
      y: 0,
      width: 50,
      height: 50,
    },
    {
      id: crypto.randomUUID(),
      component: PanelNavigator,
      x: 50,
      y: 0,
      width: 50,
      height: 50,
    },
    {
      id: crypto.randomUUID(),
      component: PanelNavigator,
      x: 0,
      y: 50,
      width: 50,
      height: 50,
    },
    {
      id: crypto.randomUUID(),
      component: PanelNavigator,
      x: 50,
      y: 50,
      width: 50,
      height: 50,
    },
  ]);

  function findNextAvailablePosition() {
    // Try to find an empty spot in a grid pattern
    const defaultSize = 33.33; // 1/3 of screen
    const positions = [
      { x: 0, y: 0 },
      { x: 33.33, y: 0 },
      { x: 66.66, y: 0 },
      { x: 0, y: 33.33 },
      { x: 33.33, y: 33.33 },
      { x: 66.66, y: 33.33 },
      { x: 0, y: 66.66 },
      { x: 33.33, y: 66.66 },
      { x: 66.66, y: 66.66 },
    ];

    // Find first position that doesn't overlap with existing panels
    for (const pos of positions) {
      const overlaps = panels.some(
        (panel) =>
          Math.abs(panel.x - pos.x) < 10 && Math.abs(panel.y - pos.y) < 10,
      );
      if (!overlaps) {
        return { x: pos.x, y: pos.y, width: defaultSize, height: defaultSize };
      }
    }

    // If all positions taken, stack on top left
    return { x: 0, y: 0, width: defaultSize, height: defaultSize };
  }

  function addPanel() {
    const position = findNextAvailablePosition();
    panels = [
      ...panels,
      {
        id: crypto.randomUUID(),
        component: PanelNavigator,
        ...position,
      },
    ];
  }
</script>

<div class="flex-1 flex-col hidden md:flex">
  <GridLayout bind:panels onAddPanel={addPanel} />
</div>

<div class="flex-1 flex-col flex md:hidden">
  <PanelNavigator />
</div>
