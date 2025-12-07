<script lang="ts">
  import { goto } from "$app/navigation";
  import ProfilePicture from "./ProfilePicture.svelte";
  import ProfilePictureCollection from "./ProfilePictureCollection.svelte";

  interface Props {
    title: string;
    tweetCount: number;
    onclick?: () => void;
  }

  let { title, tweetCount, onclick }: Props = $props();

  function formatTweetCount(count: number): string {
    if (count >= 1_000_000) {
      return `${(count / 1_000_000).toFixed(1)}M`;
    } else if (count >= 1_000) {
      return `${(count / 1_000).toFixed(1)}K`;
    }
    return count.toString();
  }
</script>

<button
  {onclick}
  class="border-t w-full border-t-stone-800 px-4 py-2 last-of-type:border-b border-b-stone-800 text-left hover:bg-stone-900"
>
  <h1 class="font-bold text-xl">{title}</h1>
  <div class="flex items-center gap-x-2">
    <ProfilePictureCollection size={20} />
    <p class="text-stone-400 font-sm">{formatTweetCount(tweetCount)} tweets</p>
  </div>
</button>
