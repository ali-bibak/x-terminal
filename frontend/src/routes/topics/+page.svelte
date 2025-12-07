<script lang="ts">
  import GridLayout from "$lib/nav/GridLayout.svelte";
  import Selection from "$lib/windows/Selection.svelte";
  import TimelinePanel from "$lib/windows/TimelinePanel.svelte";

  let panels = $state([
    {
      id: "timeline",
      component: TimelinePanel,
      x: 0,
      y: 0,
      width: 66.67,
      height: 100,
    },
    {
      id: "selection",
      component: Selection,
      x: 66.67,
      y: 0,
      width: 33.33,
      height: 100,
    },
  ]);
</script>

<GridLayout bind:panels />
