class GroupSorter:

    def sort(self, groups): #custom sorted parameter
        return sorted(
            groups,
            key=lambda g: g.strength,
            reverse=True
        )