<script lang="ts">
  import ProfilePicture from "./ProfilePicture.svelte";

  interface Props {
    count?: number;
    size?: number;
  }

  let { count = 3, size = 48 }: Props = $props();
</script>

<div class="flex items-center">
  {#each Array(count) as _, i}
    <div
      class="rounded-full border-2 border-black"
      style="margin-left: {i > 0 ? '-16px' : '0'}; z-index: {count - i};"
    >
      <ProfilePicture {size} />
    </div>
  {/each}
</div>
