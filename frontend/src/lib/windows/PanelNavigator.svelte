<script lang="ts">
  import Selection from "./Selection.svelte";
  import Timeline from "./Timeline.svelte";

  type View = "selection" | "timeline";

  let currentView = $state<View>("selection");
  let selectedTopic = $state<string>("");
  let selectedId = $state<string>("");

  function navigateToTimeline(topic: string, id: string) {
    selectedTopic = topic;
    selectedId = id;
    currentView = "timeline";
  }

  function navigateToSelection() {
    currentView = "selection";
  }
</script>

{#if currentView === "selection"}
  <Selection onNavigate={navigateToTimeline} />
{:else if currentView === "timeline"}
  <Timeline
    title={selectedTopic}
    onBack={navigateToSelection}
    id={selectedId}
  />
{/if}
