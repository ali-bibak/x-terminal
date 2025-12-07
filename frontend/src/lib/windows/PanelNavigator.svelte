<script lang="ts">
  import Selection from './Selection.svelte';
  import Timeline from './Timeline.svelte';

  type View = 'selection' | 'timeline';

  let currentView = $state<View>('selection');
  let selectedTopic = $state<string>('');

  function navigateToTimeline(topic: string) {
    selectedTopic = topic;
    currentView = 'timeline';
  }

  function navigateToSelection() {
    currentView = 'selection';
  }
</script>

{#if currentView === 'selection'}
  <Selection onNavigate={navigateToTimeline} />
{:else if currentView === 'timeline'}
  <Timeline title={selectedTopic} onBack={navigateToSelection} />
{/if}
