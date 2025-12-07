<script lang="ts">
  import type { BarResponse, FactCheckStatus } from "$lib/types";
  import { formatRelativeTime } from "$lib/utils/time";
  import { Check, X } from "lucide-svelte";

  interface Props {
    content: BarResponse;
    isLast?: boolean;
  }

  let { content, isLast = false }: Props = $props();

  let factCheckedByGrok = "HI";

  let formattedTime = $derived(formatRelativeTime(content.end));
</script>

<div class="flex gap-x-4">
  <div class="flex flex-col items-center">
    <div class="w-2 h-2 rounded-full bg-white mt-2"></div>
    {#if !isLast}
      <div
        class="w-0.5 flex-1 min-h-16 bg-linear-to-b from-stone-700 via-stone-700 to-stone-700/40"
      ></div>
    {/if}
  </div>

  <div class="flex-1">
    <p class="text-stone-400 text-sm mb-1">{formattedTime}</p>
    <p>{content.summary}</p>
    <p class="text-stone-700 text-sm mt-1 mb-2">
      {content.post_count} Posts · {content.total_likes} Likes
    </p>
    {#if factCheckedByGrok === "FALSE"}
      <div class="text-red-400 text-sm mb-1 flex flex-row items-center">
        <X class="h-4" />
        Deemed false by Grok: Some explanation
      </div>
    {:else if factCheckedByGrok === "CHECKED"}
      <div class="text-stone-400 text-sm mb-1 flex flex-row items-center">
        <Check class="h-4" />
        Fact checked by Grok
      </div>
    {/if}
  </div>
</div>
