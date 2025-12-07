<script lang="ts">
  import TopicSelection from "$lib/items/TopicSelection.svelte";

  interface Props {
    onNavigate?: (topic: string) => void;
  }

  let { onNavigate }: Props = $props();
</script>

<input
  type="text"
  placeholder="Search..."
  class="w-full px-4 py-2 border border-stone-800 rounded-full focus:outline-none focus:border-blue-400"
/>

<h1 class="font-bold text-xl mt-4">Subscribed</h1>
<div class="mt-2 -mx-4">
  <TopicSelection
    title="California Earthquake"
    tweetCount={59300}
    onclick={() => onNavigate?.("California Earthquake")}
  />
</div>

<h1 class="font-bold text-xl mt-4">Local News</h1>
<div class="mt-2 -mx-4">
  <TopicSelection
    title="Elon visits xAI"
    tweetCount={1402}
    onclick={() => onNavigate?.("Elon visits xAI")}
  />
  <TopicSelection
    title="xAI Hackathon"
    tweetCount={240828}
    onclick={() => onNavigate?.("xAI Hackathon")}
  />
</div>

<h1 class="font-bold text-xl mt-4">You'd be Interested</h1>
<div class="mt-2 -mx-4">
  <TopicSelection
    title="FSD 14.2 Released"
    tweetCount={3212839}
    onclick={() => onNavigate?.("FSD 14.2 Released")}
  />
  <TopicSelection
    title="$TSLA Earnings Call"
    tweetCount={459300}
    onclick={() => onNavigate?.("$TSLA Earnings Call")}
  />
  <TopicSelection
    title="Tottenham vs Brentford"
    tweetCount={4820}
    onclick={() => onNavigate?.("Tottenham vs Brentford")}
  />
</div>

<h1 class="font-bold text-xl mt-4">Trending</h1>
<div class="mt-2 -mx-4">
  <TopicSelection
    title="The Boys Season 5 Trailer"
    tweetCount={231232}
    onclick={() => onNavigate?.("The Boys Season 5 Trailer")}
  />
</div>
